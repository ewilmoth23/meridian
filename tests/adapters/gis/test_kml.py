"""KML / KMZ adapter tests."""

from __future__ import annotations

import zipfile

import pytest

from meridian.domain.crs import WGS84
from meridian.domain.geometry import Point2D, Polygon
from meridian.domain.parcel import Boundary, Parcel
from meridian.domain.survey import Survey


def _wgs_square():
    pts = (
        Point2D(-97.7, 30.2, WGS84),
        Point2D(-97.6, 30.2, WGS84),
        Point2D(-97.6, 30.3, WGS84),
        Point2D(-97.7, 30.3, WGS84),
        Point2D(-97.7, 30.2, WGS84),
    )
    poly = Polygon(exterior=pts).oriented()
    return Parcel(
        name="WGS Square",
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


def test_kml_export_writes_xml(tmp_path):
    pytest.importorskip("lxml")
    from meridian.adapters.gis.kml import KMLExporter

    survey = Survey(name="T", crs=WGS84)
    survey.parcels.append(_wgs_square())
    out = tmp_path / "x.kml"
    res = KMLExporter().export_survey(survey, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "<kml" in text
    assert "<Polygon>" in text
    assert "-97.7" in text
    assert res.metadata["feature_count"] == 1


def test_kmz_export_zips(tmp_path):
    pytest.importorskip("lxml")
    from meridian.adapters.gis.kml import KMLExporter

    survey = Survey(name="T", crs=WGS84)
    survey.parcels.append(_wgs_square())
    out = tmp_path / "x.kmz"
    KMLExporter().export_survey(survey, out)
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "doc.kml" in names
