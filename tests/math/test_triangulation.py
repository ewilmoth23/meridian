"""Triangulation + contour tests."""

from __future__ import annotations

import numpy as np
import pytest

from meridian.math.triangulation import (
    delaunay_2d,
    extract_contours,
    interpolate_z,
    tin_from_points,
)


def test_delaunay_unit_square():
    pts = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    tris = delaunay_2d(pts)
    # Two triangles tile the square.
    assert tris.shape == (2, 3)


def test_tin_from_points_returns_xyz():
    xyz = np.array([[0, 0, 0], [1, 0, 1], [0, 1, 2], [1, 1, 3]], dtype=np.float64)
    v, t = tin_from_points(xyz)
    assert v.shape == (4, 3)
    assert t.shape[1] == 3


def test_interpolate_z_is_exact_at_vertex():
    xyz = np.array([[0, 0, 0], [10, 0, 10], [0, 10, 20], [10, 10, 30]], dtype=np.float64)
    v, t = tin_from_points(xyz)
    z = interpolate_z(v, t, np.array([[0, 0]]))
    assert z[0] == pytest.approx(0.0)


def test_extract_contours_finds_iso_at_midplane():
    # Plane z = x (z varies linearly with x). At x=5, contour should be a vertical line.
    xs = np.linspace(0, 10, 5)
    ys = np.linspace(0, 10, 5)
    grid = np.array([[x, y, x] for x in xs for y in ys], dtype=np.float64)
    v, t = tin_from_points(grid)
    contours = extract_contours(v, t, np.array([5.0]))
    chains = contours[5.0]
    assert len(chains) >= 1
    all_pts = np.vstack(chains)
    # All points should sit on x ≈ 5.
    assert np.allclose(all_pts[:, 0], 5.0, atol=1e-6)
