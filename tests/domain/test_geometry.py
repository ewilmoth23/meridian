"""Property and golden tests for the canonical geometry types."""

from __future__ import annotations

import math

import pytest

from meridian.domain.geometry import (
    Arc,
    BBox2D,
    LineSegment,
    Point2D,
    Point3D,
    Polygon,
)


def test_point2d_distance(crs_local):
    p1 = Point2D(0, 0, crs_local)
    p2 = Point2D(3, 4, crs_local)
    assert p1.distance_to(p2) == pytest.approx(5.0)


def test_point3d_distance_horizontal_only(crs_local):
    p1 = Point3D(0, 0, 0, crs_local)
    p2 = Point3D(3, 4, 12, crs_local)
    assert p1.horizontal_distance_to(p2) == pytest.approx(5.0)
    assert p1.distance_to(p2) == pytest.approx(13.0)


def test_point_crs_mismatch_raises(crs_local, texas_central_crs):
    p1 = Point2D(0, 0, crs_local)
    p2 = Point2D(0, 1, texas_central_crs)
    with pytest.raises(ValueError):
        p1.distance_to(p2)


def test_line_bearing_north_is_zero(crs_local):
    s = Point2D(0, 0, crs_local)
    e = Point2D(0, 100, crs_local)
    assert LineSegment(s, e).bearing() == pytest.approx(0.0)


def test_line_bearing_east_is_pi_over_2(crs_local):
    s = Point2D(0, 0, crs_local)
    e = Point2D(100, 0, crs_local)
    assert LineSegment(s, e).bearing() == pytest.approx(math.pi / 2)


def test_polygon_validates_closure(crs_local):
    open_ring = (
        Point2D(0, 0, crs_local),
        Point2D(1, 0, crs_local),
        Point2D(1, 1, crs_local),
    )
    with pytest.raises(ValueError):
        Polygon(exterior=open_ring)


def test_polygon_area_unit_square(crs_local):
    ext = (
        Point2D(0, 0, crs_local),
        Point2D(1, 0, crs_local),
        Point2D(1, 1, crs_local),
        Point2D(0, 1, crs_local),
        Point2D(0, 0, crs_local),
    )
    assert Polygon(exterior=ext).area() == pytest.approx(1.0)


def test_polygon_oriented_makes_exterior_ccw(crs_local):
    cw = (
        Point2D(0, 0, crs_local),
        Point2D(0, 1, crs_local),
        Point2D(1, 1, crs_local),
        Point2D(1, 0, crs_local),
        Point2D(0, 0, crs_local),
    )
    poly = Polygon(exterior=cw)
    assert not poly.is_ccw()
    assert poly.oriented().is_ccw()


def test_arc_delta_for_known_chord(crs_local):
    s = Point2D(0, 0, crs_local)
    e = Point2D(0, 2, crs_local)
    arc = Arc(start=s, end=e, radius=1.0, clockwise=True)
    # Chord = 2R = diameter → delta = π.
    assert arc.delta() == pytest.approx(math.pi)
    assert arc.arc_length() == pytest.approx(math.pi)


def test_bbox_contains_and_expand(crs_local):
    b = BBox2D(0, 0, 10, 10, crs_local)
    assert b.contains(Point2D(5, 5, crs_local))
    assert not b.contains(Point2D(15, 5, crs_local))
    e = b.expand(2)
    assert e.contains(Point2D(-1, -1, crs_local))
