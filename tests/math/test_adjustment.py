"""Adjustment kernel tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.math.adjustment import (
    AdjustmentSpec,
    chi_square_test,
    detect_blunders,
    error_ellipse_2d,
    solve_step,
)


def test_solve_step_simple_overdetermined():
    # Fit a horizontal line y = b through 3 noisy points.
    a = np.array([[1], [1], [1]], dtype=np.float64)
    obs = np.array([10.0, 10.1, 9.9])
    spec = AdjustmentSpec(a=a, l=obs, w=np.ones(3))
    res = solve_step(spec)
    assert res.x[0] == pytest.approx(10.0, abs=1e-3)
    assert res.redundancy == 2
    assert res.cov_x.shape == (1, 1)


def test_chi_square_pass_for_unit_sigma():
    # σ₀² = 1, redundancy = 10 → chi² = 10, well within accept band for α=0.05
    assert chi_square_test(1.0, 10) is True


def test_chi_square_fail_for_huge_sigma():
    assert chi_square_test(100.0, 5) is False


def test_error_ellipse_circle_when_isotropic():
    cov = np.eye(2)
    a, b, _theta = error_ellipse_2d(cov, scale=1.0)
    assert a == pytest.approx(1.0)
    assert b == pytest.approx(1.0)


def test_error_ellipse_orientation():
    # Stretch along x: a > b, theta near 0.
    cov = np.diag([4.0, 1.0])
    a, b, theta = error_ellipse_2d(cov, scale=1.0)
    assert a == pytest.approx(2.0)
    assert b == pytest.approx(1.0)
    assert abs(math.sin(theta)) < 1e-9


def test_blunder_detection_flags_outlier():
    standardized = np.array([0.5, -0.4, 0.1, 4.5, 0.3])
    flagged = detect_blunders(standardized, threshold=3.29)
    assert flagged.tolist() == [False, False, False, True, False]
