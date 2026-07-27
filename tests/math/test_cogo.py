"""COGO unit tests — golden values + property-based round-trips."""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.math.cogo import (
    adjust_compass,
    adjust_transit,
    area_by_coordinates,
    area_by_dmd,
    back_bearing,
    bearing_difference,
    forward,
    forward_array,
    intersect_bearing_bearing,
    intersect_distance_distance,
    inverse,
    normalize_bearing,
    quadrant_bearing,
    radians_to_dms,
    run_traverse,
)


def test_inverse_round_trip():
    p1 = (1000.0, 2000.0)
    p2 = (1100.0, 2000.0)
    result = inverse(p1, p2)
    assert result.distance == pytest.approx(100.0)
    assert result.bearing == pytest.approx(math.pi / 2)


def test_forward_round_trip():
    p = (0.0, 0.0)
    end = forward(p, math.pi / 4, 100.0)
    inv = inverse(p, end)
    assert inv.distance == pytest.approx(100.0, abs=1e-9)
    assert inv.bearing == pytest.approx(math.pi / 4, abs=1e-9)


def test_normalize_bearing_wraps_full_circle():
    assert normalize_bearing(2 * math.pi + 0.1) == pytest.approx(0.1)
    assert normalize_bearing(-0.1) == pytest.approx(2 * math.pi - 0.1)


def test_back_bearing_inverts():
    b = math.radians(45)
    assert back_bearing(b) == pytest.approx(math.radians(225))


def test_bearing_difference_signed():
    assert bearing_difference(math.radians(10), math.radians(20)) == pytest.approx(math.radians(10))
    assert bearing_difference(math.radians(350), math.radians(10)) == pytest.approx(math.radians(20))
    assert bearing_difference(math.radians(10), math.radians(350)) == pytest.approx(-math.radians(20))


def test_run_traverse_perfect_square():
    res = run_traverse(
        start=(0.0, 0.0),
        bearings=[0.0, math.pi / 2, math.pi, 3 * math.pi / 2],
        distances=[100.0, 100.0, 100.0, 100.0],
    )
    assert res.closure_distance == pytest.approx(0.0, abs=1e-9)
    assert res.perimeter == pytest.approx(400.0)
    assert abs(res.area) == pytest.approx(10000.0, abs=1e-6)


def test_compass_adjustment_corrects_closure():
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.05]   # tiny error in last leg
    res = run_traverse((0.0, 0.0), bearings, distances)
    closure_dx = float(res.coordinates[-1, 0] - res.coordinates[0, 0])
    closure_dy = float(res.coordinates[-1, 1] - res.coordinates[0, 1])
    dx_adj, dy_adj = adjust_compass(bearings, distances, closure_dx, closure_dy)
    # After adjustment, the cumulative deltas should sum to (0, 0).
    assert abs(float(dx_adj.sum())) < 1e-9
    assert abs(float(dy_adj.sum())) < 1e-9


def test_transit_adjustment_corrects_closure():
    bearings = [math.radians(30), math.radians(120), math.radians(210), math.radians(300)]
    distances = [50.0, 50.0, 50.0, 50.04]
    res = run_traverse((0.0, 0.0), bearings, distances)
    closure_dx = float(res.coordinates[-1, 0] - res.coordinates[0, 0])
    closure_dy = float(res.coordinates[-1, 1] - res.coordinates[0, 1])
    dx_adj, dy_adj = adjust_transit(bearings, distances, closure_dx, closure_dy)
    assert abs(float(dx_adj.sum())) < 1e-9
    assert abs(float(dy_adj.sum())) < 1e-9


def test_area_by_dmd_matches_shoelace():
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.0]
    res = run_traverse((0.0, 0.0), bearings, distances)
    a_shoelace = area_by_coordinates(res.coordinates)
    a_dmd = area_by_dmd(bearings, distances)
    assert a_shoelace == pytest.approx(a_dmd, rel=1e-9)


def test_intersect_bearing_bearing_perpendicular():
    # Ray 1 from origin heading east; ray 2 from (100, 0) heading north — meet at (100, 0).
    p = intersect_bearing_bearing((0, 0), math.pi / 2, (100, 0), 0.0)
    assert p[0] == pytest.approx(100.0, abs=1e-9)
    assert p[1] == pytest.approx(0.0, abs=1e-9)


def test_intersect_distance_distance():
    a, b = intersect_distance_distance((0, 0), 5.0, (8, 0), 5.0)
    # Should find ~ (4, ±3)
    assert a[0] == pytest.approx(4.0)
    assert b[0] == pytest.approx(4.0)
    assert abs(a[1]) == pytest.approx(3.0)
    assert abs(b[1]) == pytest.approx(3.0)


def test_quadrant_bearing_north_east():
    quad, d, m, s = quadrant_bearing(math.radians(45.5))
    assert quad == "NE"
    assert d == 45
    assert m == 30
    assert s == pytest.approx(0.0, abs=1e-9)


def test_radians_to_dms_round_trip():
    d, m, s = radians_to_dms(math.radians(30 + 15 / 60 + 45 / 3600))
    assert d == 30
    assert m == 15
    assert s == pytest.approx(45.0, abs=1e-9)


def test_forward_array_vectorised():
    pts = forward_array((0.0, 0.0), np.array([0.0, math.pi / 2]), np.array([10.0, 20.0]))
    assert pts.shape == (2, 2)
    assert pts[0] == pytest.approx([0.0, 10.0])
    assert pts[1] == pytest.approx([20.0, 0.0])
