"""BIM bridge IFC export + reconcile tests (fallback writer path)."""

from __future__ import annotations

import pytest

from meridian.bim_bridge import export_survey_to_ifc, reconcile_intent_vs_asbuilt
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
        name="Tract 1",
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
    survey = Survey(name="BIM Test", crs=crs)
    survey.parcels.append(parcel)
    return survey


def test_ifc_fallback_writer_produces_step_file(tmp_path):
    survey = _square_survey()
    out = tmp_path / "out.ifc"
    export_survey_to_ifc(survey, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "ISO-10303-21" in text
    assert "IFCALIGNMENT" in text
    assert "IFCCARTESIANPOINT" in text


def test_reconcile_zero_deviation_when_intent_equals_asbuilt():
    survey = _square_survey()
    parcel = survey.parcels[0]
    intent = parcel.boundary.polygon  # identical
    conflict = reconcile_intent_vs_asbuilt(intent, parcel)
    assert conflict.max_deviation_m == pytest.approx(0.0, abs=1e-9)
    assert conflict.hausdorff_m == pytest.approx(0.0, abs=1e-9)


def test_reconcile_detects_offset():
    survey = _square_survey()
    parcel = survey.parcels[0]
    crs = parcel.crs
    # Build an "intent" polygon shifted by 0.5 m east.
    shifted = Polygon(
        exterior=tuple(
            Point2D(p.x + 0.5, p.y, crs) for p in parcel.boundary.polygon.exterior
        )
    ).oriented()
    conflict = reconcile_intent_vs_asbuilt(shifted, parcel)
    assert conflict.max_deviation_m == pytest.approx(0.5, abs=1e-3)
