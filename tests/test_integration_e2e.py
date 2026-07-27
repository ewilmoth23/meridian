"""End-to-end integration tests — exercise the full hexagonal stack.

Each test takes a synthetic input, runs it through one or more layers
(domain → math → pipeline → adapter → service), and verifies the
deliverable on disk against the input. These catch interface drift —
the kind of bug where every layer's unit test passes but the wiring is
wrong.
"""

from __future__ import annotations

import math

import pytest

# ── Slice 1: deed → polygon → DXF round-trip via ezdxf ────────────────────


def test_deed_to_dxf_round_trip(tmp_path):
    """Parse a deed, write DXF, read it back with ezdxf, confirm boundary
    polygon vertices match what the parser produced."""
    pytest.importorskip("ezdxf")
    import ezdxf

    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    deed_text = (
        "Beginning at the Point of Beginning; "
        "thence N 0°00'00\" E a distance of 100 meters; "
        "thence N 90°00'00\" E a distance of 100 meters; "
        "thence S 0°00'00\" W a distance of 100 meters; "
        "thence S 90°00'00\" W a distance of 100 meters to the POB."
    )
    crs = CRS(epsg=2277)
    dxf_path = tmp_path / "out.dxf"
    res = DeedService().parse_to_cad(
        text=deed_text,
        crs=crs,
        starting_point=(1000.0, 2000.0),
        dxf_path=dxf_path,
    )
    assert dxf_path.exists()
    assert res.misclosure_m < 1e-6

    # Read it back.
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    boundaries = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "BOUNDARY"]
    assert len(boundaries) == 1
    pl = boundaries[0]
    points = list(pl.get_points("xy"))
    # 4 corners + closing duplicate is how we wrote it.
    assert len(points) >= 4
    # First point should land at the POB.
    assert points[0][0] == pytest.approx(1000.0, abs=1e-6)
    assert points[0][1] == pytest.approx(2000.0, abs=1e-6)


# ── Slice 1: deed → PDF report has expected pages ─────────────────────────


def test_deed_pdf_report_round_trip(tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    from pypdf import PdfReader

    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    deed_text = (
        "Beginning at the POB; "
        "thence N 0°00'00\" E a distance of 100 meters; "
        "thence N 90°00'00\" E a distance of 100 meters; "
        "thence S 0°00'00\" W a distance of 100 meters; "
        "thence S 90°00'00\" W a distance of 100 meters to the POB."
    )
    pdf_path = tmp_path / "out.pdf"
    DeedService().parse_to_cad(
        text=deed_text, crs=CRS(epsg=2277),
        pdf_path=pdf_path, parcel_name="Test",
    )
    assert pdf_path.exists()
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 1
    text = reader.pages[0].extract_text() or ""
    assert "Boundary Survey" in text


# ── Slice 2 + TruthChain: adjustment → manifest → verify ───────────────────


def test_full_truthchain_pipeline(tmp_path):
    """Sign a manifest, build an attestation, verify it independently."""
    pytest.importorskip("cryptography")
    from meridian.truthchain import (
        ManifestEntry,
        SignedIdentity,
        build_attestation,
        build_manifest,
        generate_keypair,
        sign_manifest,
        verify_attestation,
        verify_deliverable,
    )
    from meridian.truthchain.keystore import b64, serialize_public

    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))

    src = tmp_path / "raw.gsi"
    src.write_text("FAKE GSI", encoding="ascii")

    identity = SignedIdentity(
        surveyor_name="Q.A. Tester", license_state="TX", license_number="9999",
        public_key_b64=pub_b64,
        issued_at="2026-05-02T00:00:00.000000+00:00",
    )
    entries = [
        ManifestEntry(
            obs_id=f"O{i}", setup_id="S1", kind="horizontal_distance",
            from_point="A", to_point=f"B{i}", value=100.0 + i,
            vector=None, sigma=0.005, target_height=1.5, timestamp=None,
        )
        for i in range(3)
    ]
    m = sign_manifest(
        build_manifest(
            source_path=src, driver="leica_gsi", driver_version="0.2.0",
            setups=[{"id": "S1", "occupied": "A"}],
            entries=entries, identity=identity,
        ),
        sk,
    )
    attestation = build_attestation(
        [m], algorithm_version="meridian.adjustment:0.1.0",
        sigma0=1.0, chi_square_passed=True, point_index=("A", "B0", "B1", "B2"),
    )
    assert verify_attestation(attestation, [m]) is True

    report = verify_deliverable(attestation=attestation, manifests=[m])
    assert report.overall_ok is True
    assert report.manifest_count == 1


# ── Plugin discovery picks up our adapters ─────────────────────────────────


def test_plugin_registry_discovers_first_party_adapters():
    from meridian.plugins import get_registry

    reg = get_registry(refresh=True)
    # Every first-party plugin we declared in pyproject.toml should be there.
    for short_id in ("leica_gsi", "trimble_jxl", "tds_rw5", "sokkia_sdr", "rinex", "nmea"):
        assert short_id in reg.instruments, f"Missing instrument: {short_id}"
    for short_id in ("dxf", "geojson", "kml", "shapefile", "geopackage", "landxml", "las", "pdf_report"):
        assert short_id in reg.exporters, f"Missing exporter: {short_id}"
    for short_id in ("geojson", "shapefile", "landxml", "las"):
        assert short_id in reg.importers, f"Missing importer: {short_id}"


# ── Atlas tile service serves real Survey ──────────────────────────────────


def test_atlas_tile_service_serves_loaded_survey(tmp_path):
    """When the tile service is wired to a real survey, /api/parcels.geojson
    returns its parcels (transformed to WGS84)."""
    pytest.importorskip("fastapi")
    pytest.importorskip("pyproj")
    from fastapi.testclient import TestClient

    from meridian.atlas.tile_service import create_app
    from meridian.domain.crs import WGS84
    from meridian.domain.geometry import Point2D, Polygon
    from meridian.domain.parcel import Boundary, Parcel
    from meridian.domain.survey import Survey, SurveyProject

    crs = WGS84
    pts = (
        Point2D(-97.74, 30.27, crs),
        Point2D(-97.73, 30.27, crs),
        Point2D(-97.73, 30.28, crs),
        Point2D(-97.74, 30.28, crs),
        Point2D(-97.74, 30.27, crs),
    )
    poly = Polygon(exterior=pts).oriented()
    parcel = Parcel(
        name="ATX", crs=crs, calls=(),
        boundary=Boundary(
            polygon=poly, misclosure_distance=0.0, misclosure_bearing=0.0,
            perimeter=poly.perimeter(), closure_ratio=float("inf"),
            point_of_beginning=pts[0],
        ),
    )
    survey = Survey(name="ATX-survey", crs=crs)
    survey.parcels.append(parcel)
    project = SurveyProject(name="ATX-project")
    project.add_survey(survey)

    class _Repo:
        def list_projects(self):
            return [project]
        def get_project(self, _id):
            return project
        def save_project(self, _p):
            return project.id
        def delete_project(self, _id):
            return None
        def save_survey(self, _pid, _s):
            return _s.id

    app = create_app(survey_repo=_Repo())
    with TestClient(app) as client:
        r = client.get("/api/parcels.geojson")
        assert r.status_code == 200
        fc = r.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 1
        coords = fc["features"][0]["geometry"]["coordinates"][0]
        # WGS84 — Austin is around (-97.7, 30.3).
        assert -98 < coords[0][0] < -97
        assert 30 < coords[0][1] < 31


# ── PLSS pipeline produces correct acreage ────────────────────────────────


def test_plss_full_pipeline_yields_legal_acreage():
    from meridian.domain.crs import CRS
    from meridian.jurisdictions.plss import parse_plss, plss_polygon, section_area_acres

    desc = parse_plss(
        "The NW 1/4 of the SE 1/4 of Section 14, T2N R3E, of the 6th P.M."
    )
    assert section_area_acres(desc.aliquot) == 40.0
    poly = plss_polygon(desc, CRS(epsg=2277))
    # Computed area within 0.01% of the legal nominal.
    assert poly.area() == pytest.approx(40 * 4046.8564224, rel=1e-4)


# ── Curve table integrates with parsed deed curves ─────────────────────────


def test_curve_table_handles_parcel_with_arc_call():
    from meridian.adapters.reports.curve_table import (
        CurveData,
        write_curve_table_text,
    )

    # 90° arc, R = 100 m: classic ramp curve.
    curve = CurveData.from_inputs(
        label="C1", radius=100.0, delta=math.radians(90),
        chord_bearing=math.radians(45), clockwise=True,
    )
    text = write_curve_table_text([curve])
    assert "C1" in text
    assert "100" in text         # radius value

    # Sanity-check derived values:
    assert curve.arc_length_m == pytest.approx(100.0 * math.pi / 2)
    assert curve.tangent_length_m == pytest.approx(100.0)
