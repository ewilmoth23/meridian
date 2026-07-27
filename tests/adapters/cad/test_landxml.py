"""LandXML round-trip tests."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS
from meridian.domain.geometry import Point2D, Polygon
from meridian.domain.parcel import Boundary, Parcel
from meridian.domain.survey import Survey


def _square_survey():
    crs = CRS(epsg=2277)
    pts = (
        Point2D(0, 0, crs),
        Point2D(50, 0, crs),
        Point2D(50, 50, crs),
        Point2D(0, 50, crs),
        Point2D(0, 0, crs),
    )
    poly = Polygon(exterior=pts).oriented()
    parcel = Parcel(
        name="Test Tract",
        crs=crs,
        calls=(),
        boundary=Boundary(
            polygon=poly,
            misclosure_distance=0.0,
            misclosure_bearing=0.0,
            perimeter=200.0,
            closure_ratio=float("inf"),
            point_of_beginning=pts[0],
        ),
    )
    survey = Survey(name="Test Survey", crs=crs)
    survey.parcels.append(parcel)
    return survey


def test_landxml_round_trip_preserves_polygon(tmp_path):
    pytest.importorskip("lxml")
    from meridian.adapters.cad.landxml_io import LandXMLExporter, LandXMLImporter

    survey = _square_survey()
    out = tmp_path / "out.xml"
    res = LandXMLExporter().export_survey(survey, out)
    assert out.exists()
    assert res.metadata["parcels"] == 1

    imported = LandXMLImporter().read(out)
    assert len(imported.parcels) == 1
    p = imported.parcels[0]
    assert p.name == "Test Tract"
    assert p.boundary is not None
    assert p.boundary.polygon.area() == pytest.approx(2500.0, abs=1e-3)


def test_landxml_can_read_detection(tmp_path):
    pytest.importorskip("lxml")
    from meridian.adapters.cad.landxml_io import LandXMLImporter

    survey = _square_survey()
    out = tmp_path / "out.xml"
    from meridian.adapters.cad.landxml_io import LandXMLExporter
    LandXMLExporter().export_survey(survey, out)
    importer = LandXMLImporter()
    assert importer.can_read(out)
    bogus = tmp_path / "bogus.xml"
    bogus.write_text("<?xml version='1.0'?><foo/>")
    assert not importer.can_read(bogus)
