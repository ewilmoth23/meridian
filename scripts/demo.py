#!/usr/bin/env python3
"""Meridian one-shot demo.

Generates every kind of artifact Meridian can produce — DXF, PDF, GeoJSON,
KML, HTML chain-of-title / title commitment / curve table / closure
analysis / boundary evidence — and writes them to ``out/`` (default
``/tmp/meridian-demo``). Opens an interactive list at the end.

Run with::

    python scripts/demo.py                        # writes to /tmp/meridian-demo
    python scripts/demo.py --out ~/meridian-demo  # custom location
    python scripts/demo.py --serve                # also boot Atlas globe at :8765

When ``--serve`` is set, the script blocks until you Ctrl-C; the Atlas
viewer is at http://127.0.0.1:8765/atlas/ and shows the demo parcel
near downtown Austin.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

# Project root → import meridian from src/.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Meridian demo")
    parser.add_argument("--out", default="/tmp/meridian-demo", help="Output directory")
    parser.add_argument("--serve", action="store_true", help="Boot the Atlas globe server")
    args = parser.parse_args()

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, Path] = {}

    print(f"Meridian demo — writing to {out}\n")

    # 1. Deed → DXF + PDF
    artifacts["DXF (deed → boundary)"] = _demo_deed_to_cad(out)
    artifacts["PDF (boundary report)"] = _demo_pdf_report(out)

    # 2. Multi-format export
    artifacts["GeoJSON (parcel)"] = _demo_geojson(out)
    artifacts["KML (parcel for Google Earth)"] = _demo_kml(out)
    artifacts["LandXML (round-trippable)"] = _demo_landxml(out)

    # 3. Reports
    artifacts["HTML (curve table)"] = _demo_curve_table(out)
    artifacts["HTML (closure analysis)"] = _demo_closure_report(out)
    artifacts["HTML (chain of title)"] = _demo_chain_of_title(out)
    artifacts["HTML (title commitment)"] = _demo_title_commitment(out)
    artifacts["HTML (boundary evidence)"] = _demo_boundary_evidence(out)

    # 4. PLSS
    artifacts["PLSS-derived parcel info"] = _demo_plss(out)

    # 5. TruthChain
    artifacts["TruthChain manifest + attestation"] = _demo_truthchain(out)

    # Print results.
    print("\nArtifacts produced:\n")
    for label, path in artifacts.items():
        size = path.stat().st_size if path.is_file() else "—"
        print(f"  • {label:<40} {path}  ({size} bytes)" if isinstance(size, int) else f"  • {label:<40} {path}")

    if args.serve:
        print("\nBooting Atlas globe at http://127.0.0.1:8765/atlas/ — Ctrl-C to stop.\n")
        from meridian.atlas import create_app, launch_tile_service

        app = create_app()
        handle = launch_tile_service(app, host="127.0.0.1", port=8765, daemon=False)
        print(f"  Visit: {handle.viewer_url}")
        try:
            import time
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\n  Stopped.")
    else:
        print("\nTo also boot the Atlas globe in a browser, re-run with --serve.\n")
    return 0


# ── Slice 1: deed → DXF + PDF ──────────────────────────────────────────────


_DEED_TEXT = """
BEGINNING at the Point of Beginning, an iron pin found in the southwest corner of
the property; THENCE N 0°00'00" E a distance of 100.000 meters to an iron pin set;
THENCE N 90°00'00" E a distance of 100.000 meters to an iron pin set;
THENCE S 0°00'00" W a distance of 100.000 meters to an iron pin set;
THENCE S 90°00'00" W a distance of 100.000 meters to the Point of Beginning,
containing 1.0 hectare more or less.
"""


def _demo_deed_to_cad(out: Path) -> Path:
    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    dxf_path = out / "demo.dxf"
    DeedService().parse_to_cad(
        text=_DEED_TEXT,
        crs=CRS(epsg=2277),
        starting_point=(1000.0, 2000.0),
        parcel_name="Demo Tract",
        dxf_path=dxf_path,
    )
    return dxf_path


def _demo_pdf_report(out: Path) -> Path:
    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    pdf_path = out / "demo.pdf"
    DeedService().parse_to_cad(
        text=_DEED_TEXT,
        crs=CRS(epsg=2277),
        starting_point=(1000.0, 2000.0),
        parcel_name="Demo Tract",
        pdf_path=pdf_path,
        surveyor="John Smith RPLS, TX 12345",
        client="Demo Client",
    )
    return pdf_path


# ── GIS exports ────────────────────────────────────────────────────────────


def _demo_parcel():
    from meridian.domain.crs import WGS84
    from meridian.domain.geometry import Point2D, Polygon
    from meridian.domain.parcel import Boundary, Parcel
    from meridian.domain.survey import Survey

    pts = (
        Point2D(-97.7444, 30.2672, WGS84),
        Point2D(-97.7434, 30.2672, WGS84),
        Point2D(-97.7434, 30.2682, WGS84),
        Point2D(-97.7444, 30.2682, WGS84),
        Point2D(-97.7444, 30.2672, WGS84),
    )
    poly = Polygon(exterior=pts).oriented()
    parcel = Parcel(
        name="Demo Tract — Austin TX",
        crs=WGS84,
        calls=(),
        boundary=Boundary(
            polygon=poly,
            misclosure_distance=0.0,
            misclosure_bearing=0.0,
            perimeter=poly.perimeter(),
            closure_ratio=float("inf"),
            point_of_beginning=pts[0],
        ),
    )
    survey = Survey(name="Austin Demo", crs=WGS84)
    survey.parcels.append(parcel)
    return survey


def _demo_geojson(out: Path) -> Path:
    from meridian.adapters.gis.geojson import GeoJSONExporter

    target = out / "demo.geojson"
    GeoJSONExporter().export_survey(_demo_parcel(), target)
    return target


def _demo_kml(out: Path) -> Path:
    from meridian.adapters.gis.kml import KMLExporter

    target = out / "demo.kml"
    KMLExporter().export_survey(_demo_parcel(), target)
    return target


def _demo_landxml(out: Path) -> Path:
    from meridian.adapters.cad.landxml_io import LandXMLExporter
    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point2D, Polygon
    from meridian.domain.parcel import Boundary, Parcel
    from meridian.domain.survey import Survey

    crs = CRS(epsg=2277)
    pts = (
        Point2D(0, 0, crs),
        Point2D(100, 0, crs),
        Point2D(100, 100, crs),
        Point2D(0, 100, crs),
        Point2D(0, 0, crs),
    )
    poly = Polygon(exterior=pts).oriented()
    parcel = Parcel(
        name="Demo Tract",
        crs=crs,
        calls=(),
        boundary=Boundary(
            polygon=poly,
            misclosure_distance=0.0,
            misclosure_bearing=0.0,
            perimeter=400.0,
            closure_ratio=float("inf"),
            point_of_beginning=pts[0],
        ),
    )
    survey = Survey(name="LandXML Demo", crs=crs)
    survey.parcels.append(parcel)
    target = out / "demo.xml"
    LandXMLExporter().export_survey(survey, target)
    return target


# ── HTML reports ───────────────────────────────────────────────────────────


def _demo_curve_table(out: Path) -> Path:
    from meridian.adapters.reports.curve_table import (
        CurveData,
        write_curve_table_html,
    )

    curves = [
        CurveData.from_inputs(
            label="C1", radius=100.0, delta=math.radians(90.0),
            chord_bearing=math.radians(45.0), clockwise=True,
        ),
        CurveData.from_inputs(
            label="C2", radius=50.0, delta=math.radians(60.0),
            chord_bearing=math.radians(135.0), clockwise=False,
        ),
        CurveData.from_inputs(
            label="C3", radius=250.0, delta=math.radians(35.0),
            chord_bearing=math.radians(190.0), clockwise=True,
        ),
    ]
    target = out / "curves.html"
    write_curve_table_html(curves, target, title="Demo Tract — Curve Table")
    return target


def _demo_closure_report(out: Path) -> Path:
    from meridian.adapters.reports.closure_report import (
        ClosureStandard,
        analyze,
        write_closure_report_html,
    )

    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.05]   # tiny error to demonstrate adjustment
    report = analyze(
        bearings=bearings, distances=distances,
        standard=ClosureStandard.ALTA_NSPS,
    )
    target = out / "closure.html"
    write_closure_report_html(report, target, title="Demo Tract — Closure Analysis")
    return target


def _demo_chain_of_title(out: Path) -> Path:
    from meridian.domain.deed import (
        Deed, DeedKind, Party, PartyRole, Recording,
    )
    from meridian.jurisdictions.chain_of_title import build_chain, write_chain_html

    def _deed(deed_id, grantor, grantee, year, instrument):
        return Deed(
            id=deed_id, kind=DeedKind.WARRANTY,
            parties=(
                Party(name=grantor, role=PartyRole.GRANTOR),
                Party(name=grantee, role=PartyRole.GRANTEE),
            ),
            recording=Recording(
                jurisdiction="Travis County, TX",
                instrument_number=instrument,
                recorded_date=dt.date(year, 6, 15),
            ),
        )

    deeds = [
        _deed("d1", "United States of America", "Wm. Barton",  1845, "INST-1845-001"),
        _deed("d2", "Wm. Barton",                "J. Pease",   1881, "INST-1881-217"),
        _deed("d3", "J. Pease",                  "C. Travis",  1910, "INST-1910-094"),
        _deed("d4", "C. Travis",                 "F. Robinson",1948, "INST-1948-552"),
        _deed("d5", "F. Robinson",               "Demo LLC",   2003, "INST-2003-9912"),
        # Throw in a wild deed to demonstrate defect detection.
        _deed("d-wild", "Stranger McNobody",     "Demo LLC",   2010, "INST-2010-WILD"),
    ]
    chain = build_chain("demo-parcel", deeds)
    target = out / "chain_of_title.html"
    write_chain_html(chain, target)
    return target


def _demo_title_commitment(out: Path) -> Path:
    from meridian.jurisdictions.title_commitment import (
        parse_title_commitment,
        write_commitment_report_html,
    )

    sample = """
    SCHEDULE A
    Effective Date: April 15, 2026
    Proposed Insured: First National Bank of Springfield
    The estate or interest in the Land insured by this Commitment is: Fee Simple
    Title is vested in: Demo LLC, a Texas limited liability company
    Land referred to: Lot 5, Block 2, Sunset Acres Subdivision, Travis County, TX
    Policy Amount: $450,000.00

    SCHEDULE B-I REQUIREMENTS
    1. Pay the agreed amount for the title insurance.
    2. Obtain payoff and release of mortgage to ABC Bank recorded in Vol. 234, Pg. 56.
    3. Survey of the subject property must be obtained and reviewed.
    4. Affidavit of debts and liens executed by the Sellers.
    5. Probate of estate of John Doe; Letters Testamentary required.

    SCHEDULE B-II EXCEPTIONS
    1. Taxes for the year 2026, a lien not yet due and payable.
    2. Easement granted to Springfield Power and Light recorded May 1, 1972, Inst. No. 19720501.
    3. Restrictive covenants and conditions recorded in Vol. 100, Pg. 200.
    4. Mineral reservation in deed from John Smith to Jane Smith recorded April 2, 1995.
    5. Rights of parties in possession.
    6. Drainage easement granted to Travis County recorded August 12, 1988.
    """
    commitment = parse_title_commitment(sample)
    target = out / "title_commitment.html"
    write_commitment_report_html(commitment, target)
    return target


def _demo_boundary_evidence(out: Path) -> Path:
    from meridian.jurisdictions.boundary_evidence import (
        BoundaryEvidence,
        EvidenceKind,
        determine_boundary,
        write_evidence_report_html,
    )

    evidence = [
        BoundaryEvidence("E1", EvidenceKind.NATURAL_MONUMENT,        100.00, 200.00, 0.10),
        BoundaryEvidence("E2", EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 100.02, 200.04, 0.03),
        BoundaryEvidence("E3", EvidenceKind.DEED_CALL_BEARING,       100.10, 200.05, 0.30),
        BoundaryEvidence("E4", EvidenceKind.DEED_CALL_DISTANCE,      100.50, 200.20, 0.50),
        BoundaryEvidence("E5", EvidenceKind.OCCUPATION_LINE,         100.15, 200.18, 0.20),
        BoundaryEvidence("E6", EvidenceKind.GNSS_OBSERVATION,         99.95, 200.02, 0.05),
        # A blunder we expect the rejector to catch:
        BoundaryEvidence("E7-blunder", EvidenceKind.AERIAL_PHOTO,    115.00, 220.00, 0.40),
    ]
    determination = determine_boundary(evidence, state="TX")
    target = out / "boundary_evidence.html"
    write_evidence_report_html(evidence, determination, target)
    return target


# ── PLSS ───────────────────────────────────────────────────────────────────


def _demo_plss(out: Path) -> Path:
    from meridian.jurisdictions.plss import parse_plss

    descs = [
        "The Northwest 1/4 of Section 14, Township 2 North, Range 3 East, of the 6th Principal Meridian",
        "NE 1/4 of the SW 1/4 of Section 7, T1S R2W, Mount Diablo Meridian",
        "Section 36, T5N R8E, Salt Lake Meridian",
    ]
    target = out / "plss.txt"
    lines = []
    for d in descs:
        parsed = parse_plss(d)
        lines.append(f"INPUT:    {d}")
        lines.append(f"PARSED:   {parsed.label()}")
        lines.append(f"MERIDIAN: {parsed.township_range.meridian}")
        lines.append("")
    target.write_text("\n".join(lines))
    return target


# ── TruthChain ─────────────────────────────────────────────────────────────


def _demo_truthchain(out: Path) -> Path:
    from meridian.truthchain import (
        ManifestEntry,
        SignedIdentity,
        build_attestation,
        build_manifest,
        generate_keypair,
        sign_manifest,
    )
    from meridian.truthchain.keystore import b64, serialize_public

    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))

    raw = out / "raw.gsi"
    raw.write_text("FAKE GSI CONTENT FOR DEMO\n", encoding="ascii")
    identity = SignedIdentity(
        surveyor_name="John Smith RPLS",
        license_state="TX",
        license_number="12345",
        public_key_b64=pub_b64,
        issued_at=dt.datetime.now(dt.UTC).isoformat(timespec="microseconds"),
    )
    entries = [
        ManifestEntry(
            obs_id=f"O{i}", setup_id="S1", kind="horizontal_distance",
            from_point="A", to_point=f"B{i}", value=10.0 + i,
            vector=None, sigma=0.005, target_height=1.5, timestamp=None,
        )
        for i in range(4)
    ]
    manifest = sign_manifest(
        build_manifest(
            source_path=raw, driver="leica_gsi", driver_version="0.2.0",
            setups=[{"id": "S1", "occupied": "A"}],
            entries=entries, identity=identity,
        ),
        sk,
    )
    attestation = build_attestation(
        [manifest],
        algorithm_version="meridian.adjustment:0.1.0",
        sigma0=1.001, chi_square_passed=True,
        point_index=("A", "B0", "B1", "B2", "B3"),
    )
    manifest_path = out / "demo.manifest.json"
    manifest_path.write_text(manifest.to_json(indent=2), encoding="utf-8")
    attestation_path = out / "demo.attestation.json"
    attestation_path.write_text(attestation.to_json(), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    sys.exit(main())
