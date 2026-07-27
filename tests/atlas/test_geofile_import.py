"""Tests for ``meridian.atlas.geofile_import`` and the geofile REST endpoint."""

from __future__ import annotations

import io
from pathlib import Path

import ezdxf
import laspy
import numpy as np
import pytest
from fastapi.testclient import TestClient

from meridian.atlas import create_app
from meridian.atlas.bookmarks import BookmarkStore
from meridian.atlas.geofile_import import (
    detect_and_import,
    import_dxf,
    import_landxml,
    import_las,
)
from meridian.atlas.presentations import PresentationStore

# ── DXF ─────────────────────────────────────────────────────────────────────


def _make_dxf_bytes() -> bytes:
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "BOUNDARY"})
    msp.add_circle((50, 25), 10, dxfattribs={"layer": "MARKER"})
    msp.add_line((0, 0), (100, 100), dxfattribs={"layer": "TIE"})
    msp.add_text("PT-1", dxfattribs={"insert": (20, 30, 0), "layer": "LABELS"})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def test_dxf_extracts_features_and_layers():
    result = import_dxf(_make_dxf_bytes())
    fc = result.feature_collection
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 4
    layers = {f["properties"]["layer"] for f in fc["features"]}
    assert layers == {"BOUNDARY", "MARKER", "TIE", "LABELS"}


def test_dxf_lwpolyline_closed_becomes_polygon():
    result = import_dxf(_make_dxf_bytes())
    boundary = next(f for f in result.feature_collection["features"] if f["properties"]["layer"] == "BOUNDARY")
    assert boundary["geometry"]["type"] == "Polygon"
    ring = boundary["geometry"]["coordinates"][0]
    # First and last point match (closed ring).
    assert ring[0] == ring[-1]


def test_dxf_circle_becomes_polygon():
    result = import_dxf(_make_dxf_bytes())
    marker = next(f for f in result.feature_collection["features"] if f["properties"]["layer"] == "MARKER")
    assert marker["geometry"]["type"] == "Polygon"
    assert marker["properties"]["radius"] == 10
    # Circle approximated to many segments.
    assert len(marker["geometry"]["coordinates"][0]) > 16


def test_dxf_line_becomes_linestring():
    result = import_dxf(_make_dxf_bytes())
    line = next(f for f in result.feature_collection["features"] if f["properties"]["layer"] == "TIE")
    assert line["geometry"]["type"] == "LineString"
    assert len(line["geometry"]["coordinates"]) == 2


def test_dxf_text_becomes_point_with_text_property():
    result = import_dxf(_make_dxf_bytes())
    text = next(f for f in result.feature_collection["features"] if f["properties"]["layer"] == "LABELS")
    assert text["geometry"]["type"] == "Point"
    assert text["properties"]["text"] == "PT-1"


def test_dxf_summary_has_bbox_and_layers():
    result = import_dxf(_make_dxf_bytes())
    s = result.summary
    assert s["format"] == "dxf"
    assert s["feature_count"] == 4
    assert "BOUNDARY" in s["layers"]
    assert s["bbox"] is not None
    assert len(s["bbox"]) == 4


def test_dxf_with_state_plane_source_crs_transforms_to_lonlat():
    """Regression: a DXF with FL East state-plane coords (EPSG:2236) must
    transform to lon/lat in Florida when source_crs_epsg is given. This
    is the bug that made DXF imports invisible — coords stayed in raw
    state-plane and Cesium couldn't render them."""
    import io

    import ezdxf

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    # Realistic Polk County, FL coordinates in EPSG:2236 (US ft).
    msp.add_line((670000, 1380000), (670500, 1380500))
    msp.add_lwpolyline(
        [(670000, 1380000), (670500, 1380000), (670500, 1380500), (670000, 1380500)],
        close=True,
    )
    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode("utf-8")

    # Without source_crs_epsg → coords stay in state-plane (broken)
    raw = import_dxf(data)
    raw_first = raw.feature_collection["features"][0]
    assert raw_first["geometry"]["coordinates"][0][0] > 100  # state-plane easting

    # With source_crs_epsg → coords transformed to WGS84 lon/lat
    fixed = import_dxf(data, source_crs_epsg=2236)
    fixed_first = fixed.feature_collection["features"][0]
    lon, lat = fixed_first["geometry"]["coordinates"][0][:2]
    assert -83 < lon < -80, f"lon {lon} not in Florida range"
    assert 27 < lat < 29, f"lat {lat} not in Florida range"


def test_dxf_recover_extracts_entities_real_world_files():
    """Regression: the previous parser used ezdxf.read(StringIO(decoded))
    which silently produced 0 entities for many real-world DXFs (the bytes
    decoded fine but the entities never made it past the parser).

    The fix uses ezdxf.recover.read(BytesIO) which handles binary input
    correctly. Build a DXF programmatically, write it the same way ezdxf
    does, parse it back, and confirm we get all entities."""
    import io

    import ezdxf

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 10))
    msp.add_line((10, 10), (20, 0))
    msp.add_circle((5, 5), radius=3)
    msp.add_lwpolyline([(0, 0), (5, 0), (5, 5), (0, 5)], close=True)

    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode("utf-8")

    result = import_dxf(data)
    feats = result.feature_collection["features"]
    assert len(feats) == 4, f"expected 4 features, got {len(feats)}"
    types = sorted(f["geometry"]["type"] for f in feats)
    assert types == ["LineString", "LineString", "Polygon", "Polygon"]


def test_dxf_fragment_with_no_header_is_recovered_via_manual_parser():
    """Regression: laser-cutter / mechanical-CAD tools sometimes emit
    fragment DXFs that contain only an ENTITIES section, no HEADER or
    TABLES. ezdxf rejects those outright. The manual fallback parser
    must extract the primitives."""
    fragment = b"""0
SECTION
2
ENTITIES

0
LWPOLYLINE
8
0
90
4
70
1
10
0
20
0
10
320
20
0
10
320
20
220
10
0
20
220

0
CIRCLE
8
0
10
10
20
10
40
1.6

0
ENDSEC
0
EOF
"""
    result = import_dxf(fragment)
    feats = result.feature_collection["features"]
    assert len(feats) == 2, f"expected 2 features, got {len(feats)}"
    geom_types = sorted(f["geometry"]["type"] for f in feats)
    assert geom_types == ["Polygon", "Polygon"], f"got {geom_types}"
    # The summary should record that the manual fallback was used.
    assert result.summary.get("parser") == "manual_fallback"


def test_dxf_invalid_bytes_raise_valueerror():
    with pytest.raises(ValueError, match="DXF parse failed"):
        import_dxf(b"definitely not a DXF file")


# ── LAS ─────────────────────────────────────────────────────────────────────


def _make_las_bytes(n: int = 1000) -> bytes:
    header = laspy.LasHeader(version="1.4", point_format=6)
    las = laspy.LasData(header)
    las.x = np.arange(n, dtype=float)
    las.y = np.arange(n, dtype=float) * 1.5
    las.z = np.linspace(100, 200, n)
    las.classification = np.array([2 if i % 3 == 0 else 5 if i % 3 == 1 else 6 for i in range(n)], dtype=np.uint8)
    las.intensity = np.linspace(0, 1000, n).astype(np.uint16)
    out = io.BytesIO()
    las.write(out)
    return out.getvalue()


def test_las_returns_multipoint_feature():
    result = import_las(_make_las_bytes(500))
    fc = result.feature_collection
    assert len(fc["features"]) == 1
    feat = fc["features"][0]
    assert feat["geometry"]["type"] == "MultiPoint"
    assert len(feat["geometry"]["coordinates"]) == 500


def test_las_subsamples_when_over_max_points():
    result = import_las(_make_las_bytes(10_000), max_points=1_000)
    feat = result.feature_collection["features"][0]
    # stride = 10000 // 1000 = 10 → kept ~1000 points (numpy slicing rounds up).
    assert 900 <= len(feat["geometry"]["coordinates"]) <= 1100
    assert result.summary["stride"] == 10


def test_las_classification_histogram():
    result = import_las(_make_las_bytes(99))  # 33 each of classes 2, 5, 6
    hist = result.summary["classification_histogram"]
    assert hist["2"] == 33
    assert hist["5"] == 33
    assert hist["6"] == 33


def test_las_per_point_colors_match_class():
    result = import_las(_make_las_bytes(30))
    feat = result.feature_collection["features"][0]
    classes = feat["properties"]["classifications"]
    colors = feat["properties"]["colors"]
    # Class 2 (ground) → brown; class 5 (high veg) → forest green.
    for c, col in zip(classes, colors, strict=True):
        if c == 2:
            assert col == "#a86b3c"
        elif c == 5:
            assert col == "#1a7b4a"


def test_las_summary_has_bbox():
    result = import_las(_make_las_bytes(50))
    bbox = result.summary["bbox"]
    assert len(bbox) == 6   # (minx, miny, minz, maxx, maxy, maxz)
    assert bbox[0] < bbox[3]
    assert bbox[1] < bbox[4]
    assert bbox[2] < bbox[5]


def test_las_invalid_bytes_raise_valueerror():
    with pytest.raises(ValueError, match="LAS/LAZ parse failed"):
        import_las(b"not a las file")


# ── LandXML ────────────────────────────────────────────────────────────────


_LANDXML = b"""<?xml version="1.0" encoding="UTF-8"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <Surfaces>
    <Surface name="Surface1">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">100 200 50</P>
          <P id="2">100 210 51</P>
          <P id="3">110 200 52</P>
          <P id="4">110 210 53</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
          <F>2 4 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
  <Parcels>
    <Parcel name="Lot 1">
      <CoordGeom>
        <Line><Start>100 200</Start><End>110 200</End></Line>
        <Line><Start>110 200</Start><End>110 210</End></Line>
        <Line><Start>110 210</Start><End>100 210</End></Line>
        <Line><Start>100 210</Start><End>100 200</End></Line>
      </CoordGeom>
    </Parcel>
  </Parcels>
</LandXML>
"""


def test_landxml_extracts_surfaces_and_parcels():
    result = import_landxml(_LANDXML)
    assert result.summary["surface_count"] == 1
    assert result.summary["parcel_count"] == 1
    feats = result.feature_collection["features"]
    surfaces = [f for f in feats if f["properties"]["layer"].startswith("surface:")]
    parcels = [f for f in feats if f["properties"]["layer"] == "parcels"]
    assert len(surfaces) == 2  # two TIN faces
    assert len(parcels) == 1


def test_landxml_parcel_coordinates_have_z():
    result = import_landxml(_LANDXML)
    parcel = next(f for f in result.feature_collection["features"] if f["properties"]["layer"] == "parcels")
    ring = parcel["geometry"]["coordinates"][0]
    for pt in ring:
        assert len(pt) == 3


def test_landxml_invalid_xml_raises_valueerror():
    with pytest.raises(ValueError, match="LandXML parse failed"):
        import_landxml(b"<not xml")


# ── Format dispatch ─────────────────────────────────────────────────────────


def test_detect_dxf():
    result = detect_and_import("foo.dxf", _make_dxf_bytes())
    assert result.summary["format"] == "dxf"


def test_detect_las():
    result = detect_and_import("foo.las", _make_las_bytes(20))
    assert result.summary["format"] == "las"


def test_detect_laz_alias():
    # .laz is the same parser path as .las for laspy >= 2.5.
    result = detect_and_import("foo.laz", _make_las_bytes(20))
    assert result.summary["format"] == "las"


def test_detect_landxml_extensions():
    a = detect_and_import("plat.xml", _LANDXML)
    b = detect_and_import("plat.landxml", _LANDXML)
    assert a.summary["format"] == "landxml"
    assert b.summary["format"] == "landxml"


def test_detect_unsupported_extension_raises():
    with pytest.raises(ValueError, match="Unsupported geofile"):
        detect_and_import("foo.png", b"x")


# ── REST endpoint ──────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(
        presentation_store=PresentationStore(directory=tmp_path / "p"),
        bookmark_store=BookmarkStore(path=tmp_path / "bookmarks.json"),
    ))


def test_geofile_import_endpoint_dxf(client):
    r = client.post("/api/geofile/import?filename=demo.dxf", content=_make_dxf_bytes())
    assert r.status_code == 200
    body = r.json()
    assert body["feature_collection"]["type"] == "FeatureCollection"
    assert len(body["feature_collection"]["features"]) == 4


def test_geofile_import_endpoint_las(client):
    r = client.post("/api/geofile/import?filename=cloud.las", content=_make_las_bytes(50))
    assert r.status_code == 200
    body = r.json()
    feat = body["feature_collection"]["features"][0]
    assert feat["geometry"]["type"] == "MultiPoint"
    assert feat["properties"]["kept"] == 50


def test_geofile_import_unsupported_returns_400(client):
    r = client.post("/api/geofile/import?filename=foo.png", content=b"x")
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_geofile_import_empty_body_returns_400(client):
    r = client.post("/api/geofile/import?filename=foo.dxf", content=b"")
    assert r.status_code == 400


def test_geofile_import_bad_dxf_returns_400(client):
    r = client.post("/api/geofile/import?filename=foo.dxf", content=b"not dxf bytes")
    assert r.status_code == 400
    assert "DXF" in r.json()["detail"]
