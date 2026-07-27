"""Easement analyzer tests."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS
from meridian.jurisdictions.easement import (
    Easement,
    EasementOrigin,
    EasementPurpose,
    detect_conflicts,
    easement_strip_polygon,
    easement_to_polygon,
    encumbered_area,
    parallel_offset,
    write_easement_report_html,
)


def _straight_easement(name="E1", width=10.0):
    return Easement(
        name=name,
        purpose=EasementPurpose.UTILITY,
        origin=EasementOrigin.EXPRESS_GRANT,
        centerline=((0.0, 0.0), (100.0, 0.0)),
        width_m=width,
    )


# ── parallel_offset ───────────────────────────────────────────────────────


def test_parallel_offset_straight_line_left():
    coords = parallel_offset([(0, 0), (100, 0)], 5.0, side="left")
    # Left of an east-pointing line is +y.
    assert coords[0] == pytest.approx([0.0, 5.0])
    assert coords[-1] == pytest.approx([100.0, 5.0])


def test_parallel_offset_straight_line_right():
    coords = parallel_offset([(0, 0), (100, 0)], 5.0, side="right")
    assert coords[0] == pytest.approx([0.0, -5.0])
    assert coords[-1] == pytest.approx([100.0, -5.0])


def test_parallel_offset_rejects_single_point():
    with pytest.raises(ValueError, match="at least 2"):
        parallel_offset([(0, 0)], 5.0)


def test_parallel_offset_l_shaped_line():
    # Right-angle turn at (100, 0): segment 1 east, segment 2 north.
    coords = parallel_offset([(0, 0), (100, 0), (100, 100)], 5.0, side="left")
    # First point shifted +y; turn point shifted along bisector.
    assert coords[0][1] == pytest.approx(5.0)
    assert coords[2][0] == pytest.approx(95.0)


# ── strip generation ──────────────────────────────────────────────────────


def test_strip_polygon_is_closed_rectangle():
    e = _straight_easement(width=10.0)
    coords = easement_strip_polygon(e)
    # Closed: first ≡ last.
    assert coords[0] == pytest.approx(coords[-1])
    # Rectangle 100m × 10m → 4 distinct corners.
    distinct = {tuple(p) for p in coords[:-1]}
    assert len(distinct) == 4


def test_easement_to_polygon_area_matches_width_x_length():
    crs = CRS(epsg=2277)
    e = _straight_easement(width=10.0)
    poly = easement_to_polygon(e, crs)
    assert poly.area() == pytest.approx(100.0 * 10.0, rel=1e-6)


# ── encumbrance + conflicts ──────────────────────────────────────────────


def test_encumbered_area_two_disjoint_easements():
    e1 = _straight_easement(name="E1", width=10.0)
    e2 = Easement(
        name="E2",
        purpose=EasementPurpose.DRAINAGE,
        origin=EasementOrigin.EXPRESS_GRANT,
        centerline=((0.0, 50.0), (100.0, 50.0)),    # parallel, far away
        width_m=8.0,
    )
    total = encumbered_area([e1, e2])
    # 100×10 + 100×8 = 1800
    assert total == pytest.approx(1800.0, rel=1e-3)


def test_detect_conflict_for_overlapping_strips():
    e1 = _straight_easement(name="E1", width=10.0)
    e2 = Easement(
        name="E2",
        purpose=EasementPurpose.UTILITY,
        origin=EasementOrigin.EXPRESS_GRANT,
        centerline=((50.0, -2.0), (50.0, 2.0)),     # crosses E1 perpendicularly
        width_m=10.0,
    )
    conflicts = detect_conflicts([e1, e2])
    assert len(conflicts) >= 1
    assert conflicts[0].overlap_area_m2 > 1.0


def test_detect_conflict_zero_for_disjoint_strips():
    e1 = _straight_easement(name="E1", width=10.0)
    e2 = Easement(
        name="E2",
        purpose=EasementPurpose.UTILITY,
        origin=EasementOrigin.EXPRESS_GRANT,
        centerline=((0.0, 1000.0), (100.0, 1000.0)),
        width_m=10.0,
    )
    conflicts = detect_conflicts([e1, e2])
    assert conflicts == []


# ── HTML report ───────────────────────────────────────────────────────────


def test_easement_report_html_writes(tmp_path):
    e1 = _straight_easement(name="E1")
    out = tmp_path / "easements.html"
    write_easement_report_html([e1], [], out)
    text = out.read_text()
    assert "Easement Analysis" in text
    assert "E1" in text
