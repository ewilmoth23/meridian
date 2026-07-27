"""GeoJSON adapter tests."""

from __future__ import annotations

import json

import pytest

from meridian.adapters.gis.geojson import GeoJSONExporter, GeoJSONImporter
from meridian.domain.crs import CRS, WGS84
from meridian.domain.geometry import Point2D, Polygon
from meridian.domain.parcel import Boundary, Parcel
from meridian.domain.survey import Survey


def _square(crs):
    pts = (
        Point2D(0, 0, crs),
        Point2D(100, 0, crs),
        Point2D(100, 100, crs),
        Point2D(0, 100, crs),
        Point2D(0, 0, crs),
    )
    poly = Polygon(exterior=pts).oriented()
    boundary = Boundary(
        polygon=poly,
        misclosure_distance=0.0,
        misclosure_bearing=0.0,
        perimeter=400.0,
        closure_ratio=float("inf"),
        point_of_beginning=pts[0],
    )
    return Parcel(name="A", crs=crs, calls=(), boundary=boundary)


def test_geojson_export_other_crs_passthrough(tmp_path):
    crs = CRS(epsg=2277)
    survey = Survey(name="T", crs=crs)
    survey.parcels.append(_square(crs))
    out = tmp_path / "x.geojson"
    res = GeoJSONExporter().export_survey(survey, out, allow_other_crs=True)
    data = json.loads(out.read_text())
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    coords = data["features"][0]["geometry"]["coordinates"][0]
    # Coordinates left in source CRS
    assert coords[0] == [0.0, 0.0]
    assert coords[2] == [100.0, 100.0]
    assert res.metadata["rfc7946"] is False


def test_geojson_export_rfc7946_transforms_to_wgs84(tmp_path):
    crs = WGS84
    survey = Survey(name="T", crs=crs)
    survey.parcels.append(_square(crs))
    out = tmp_path / "x.geojson"
    GeoJSONExporter().export_survey(survey, out)
    data = json.loads(out.read_text())
    coords = data["features"][0]["geometry"]["coordinates"][0]
    assert coords[0] == [0.0, 0.0]


def test_geojson_import_returns_parcel(tmp_path):
    src = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "properties": {"name": "Lot 1", "apn": "TX-123"},
            }
        ],
    }
    p = tmp_path / "in.geojson"
    p.write_text(json.dumps(src))
    importer = GeoJSONImporter()
    assert importer.can_read(p)
    res = importer.read(p)
    assert len(res.parcels) == 1
    parcel = res.parcels[0]
    assert parcel.name == "Lot 1"
    assert parcel.boundary is not None
    assert parcel.boundary.polygon.area() == pytest.approx(100.0)


def test_geojson_round_trip_preserves_geometry(tmp_path):
    crs = CRS(epsg=2277)
    survey = Survey(name="T", crs=crs)
    survey.parcels.append(_square(crs))
    out = tmp_path / "x.geojson"
    GeoJSONExporter().export_survey(survey, out, allow_other_crs=True)
    res = GeoJSONImporter().read(out, crs=crs)
    assert len(res.parcels) == 1
    p = res.parcels[0].boundary.polygon  # type: ignore[union-attr]
    assert p.area() == pytest.approx(10000.0)
