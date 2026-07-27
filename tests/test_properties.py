"""Property-based fuzz tests on COGO and adjustment math.

Each test states an invariant Meridian's math is supposed to obey:

* ``inverse(forward(p, b, d))`` round-trips to the same b, d.
* Compass-rule adjustment preserves perimeter sum.
* Polygon area is invariant under translation.
* Bearing normalisation is idempotent.

Hypothesis searches for inputs that break the invariant. Anything that
slips past the unit tests usually surfaces here.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from meridian.math.cogo import (
    adjust_compass,
    area_by_coordinates,
    back_bearing,
    bearing_difference,
    forward,
    inverse,
    normalize_bearing,
    run_traverse,
)

# Strategies — generate sane survey-scale geometry.
finite_coord = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
positive_distance = st.floats(min_value=0.001, max_value=1e5, allow_nan=False, allow_infinity=False)
bearing_rad = st.floats(min_value=0.0, max_value=2 * math.pi, allow_nan=False, allow_infinity=False, exclude_max=True)


# ── Forward / inverse round-trip ──────────────────────────────────────────


@given(p1x=finite_coord, p1y=finite_coord, b=bearing_rad, d=positive_distance)
@settings(max_examples=200, deadline=None)
def test_forward_inverse_round_trip(p1x, p1y, b, d):
    """forward → inverse returns the same bearing (mod 2π) and distance."""
    p2 = forward((p1x, p1y), b, d)
    res = inverse((p1x, p1y), p2)
    assert res.distance == pytest.approx(d, rel=1e-6, abs=1e-6)
    expected = normalize_bearing(b)
    actual = normalize_bearing(res.bearing)
    diff = abs(actual - expected)
    diff = min(diff, 2 * math.pi - diff)         # circular distance
    assert diff < 1e-6


# ── Bearing normalisation ─────────────────────────────────────────────────


@given(angle=st.floats(min_value=-1e3 * math.pi, max_value=1e3 * math.pi, allow_nan=False, allow_infinity=False))
def test_normalize_bearing_in_range(angle):
    n = normalize_bearing(angle)
    assert 0.0 <= n < 2 * math.pi + 1e-12


@given(angle=st.floats(min_value=0.0, max_value=2 * math.pi, allow_nan=False, allow_infinity=False, exclude_max=True))
def test_normalize_bearing_idempotent(angle):
    once = normalize_bearing(angle)
    twice = normalize_bearing(once)
    assert once == pytest.approx(twice)


@given(angle=bearing_rad)
def test_back_bearing_double_inverts(angle):
    """back(back(b)) ≡ b (mod 2π). Tolerance acknowledges FP wrap near 2π."""
    expected = normalize_bearing(angle)
    actual = normalize_bearing(back_bearing(back_bearing(angle)))
    # Use circular distance: the two should be either ~equal or ~2π apart.
    diff = abs(actual - expected)
    diff = min(diff, 2 * math.pi - diff)
    assert diff < 1e-9


@given(a=bearing_rad, b=bearing_rad)
def test_bearing_difference_in_range(a, b):
    d = bearing_difference(a, b)
    assert -math.pi - 1e-9 <= d <= math.pi + 1e-9


# ── Closed traverse ───────────────────────────────────────────────────────


@st.composite
def closed_traverse(draw, n=4):
    """Generate a closed traverse with N legs."""
    bearings = [draw(bearing_rad) for _ in range(n)]
    distances = [draw(positive_distance) for _ in range(n)]
    return bearings, distances


@given(traverse=closed_traverse(n=4))
@settings(max_examples=100, deadline=None)
def test_compass_rule_zeroes_out_closure_error(traverse):
    bearings, distances = traverse
    res = run_traverse((0.0, 0.0), bearings, distances)
    closure_dx = float(res.coordinates[-1, 0] - 0.0)
    closure_dy = float(res.coordinates[-1, 1] - 0.0)
    assume(sum(distances) > 1e-3)  # the adjustment requires nonzero perimeter
    dx_adj, dy_adj = adjust_compass(bearings, distances, closure_dx, closure_dy)
    # After adjustment, the cumulative sum must close.
    assert abs(float(dx_adj.sum())) < 1e-6
    assert abs(float(dy_adj.sum())) < 1e-6


# ── Polygon area invariance under translation ─────────────────────────────


@given(
    n=st.integers(min_value=3, max_value=12),
    tx=finite_coord,
    ty=finite_coord,
    seed=st.integers(min_value=0, max_value=1_000_000),
)
@settings(max_examples=100, deadline=None)
def test_polygon_area_invariant_under_translation(n, tx, ty, seed):
    """Translating a polygon does not change its area."""
    rng = np.random.default_rng(seed)
    # Generate `n` points on a regular polygon with random radius/start angle.
    radius = float(rng.uniform(1.0, 100.0))
    start = float(rng.uniform(0, 2 * math.pi))
    coords = np.array(
        [
            (radius * math.cos(start + 2 * math.pi * i / n),
             radius * math.sin(start + 2 * math.pi * i / n))
            for i in range(n)
        ]
        + [(radius * math.cos(start), radius * math.sin(start))],
        dtype=np.float64,
    )
    a1 = area_by_coordinates(coords)
    coords[:, 0] += tx
    coords[:, 1] += ty
    a2 = area_by_coordinates(coords)
    assert a1 == pytest.approx(a2, rel=1e-9, abs=1e-6)


# ── Inverse-distance invariance under coordinate flip ─────────────────────


@given(p1x=finite_coord, p1y=finite_coord, p2x=finite_coord, p2y=finite_coord)
def test_inverse_distance_symmetric(p1x, p1y, p2x, p2y):
    """``inverse(p1, p2).distance == inverse(p2, p1).distance``."""
    d1 = inverse((p1x, p1y), (p2x, p2y)).distance
    d2 = inverse((p2x, p2y), (p1x, p1y)).distance
    assert d1 == pytest.approx(d2, rel=1e-9, abs=1e-9)
