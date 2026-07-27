"""Least-squares network adjustment.

A proper Gauss-Newton adjustment using ``scipy.linalg`` (Cholesky / QR for
the normal equations) and ``scipy.sparse`` for large networks. Replaces
the prototype's pure-Python Gauss-Jordan implementation, which was both
numerically unstable and wrong (didn't actually solve a weighted LS
problem).

This module is the **engine**. A higher-level pipeline in
:mod:`meridian.pipelines.network_adjust` wraps it so callers pass in
domain :class:`~meridian.domain.network.ControlNetwork` objects and get
:class:`~meridian.domain.network.NetworkAdjustment` objects back.

Algorithm overview
------------------
We solve the weighted least-squares problem

    minimize  v^T W v
    subject to A x = l - v

where:
* ``A`` is the Jacobian of observation equations w.r.t. unknown coords
* ``x`` is the parameter correction vector (Δx, Δy, Δz per unknown point)
* ``l`` is the observed-minus-computed vector
* ``W = diag(1/σ²)`` is the weight matrix
* ``v`` is the vector of residuals

Iterating Gauss-Newton until ``|x| < tolerance`` produces the adjusted
parameters and a posterior covariance matrix
``Cx = (A^T W A)^-1 * σ0²``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import scipy.linalg as la

# Internal types — the pipeline layer translates between these and
# meridian.domain.* entities.


@dataclass(slots=True)
class AdjustmentSpec:
    """Inputs for a single Gauss-Newton iteration.

    Attributes
    ----------
    a
        Jacobian / design matrix, shape ``(M, N)``. ``M`` = observations,
        ``N`` = unknown parameters.
    l
        Observed-minus-computed vector, shape ``(M,)``.
    w
        Weight matrix as a 1-D vector of diagonal entries (``1/σ²``),
        shape ``(M,)``. We assume diagonal weights here; correlated
        observations would extend this to a full matrix.

    """

    a: np.ndarray
    l: np.ndarray
    w: np.ndarray


@dataclass(slots=True)
class AdjustmentResult:
    """Result of one Gauss-Newton step."""

    x: np.ndarray            # parameter corrections, shape (N,)
    v: np.ndarray            # residuals, shape (M,)
    sigma0_sq: float         # reference variance a posteriori
    redundancy: int          # M - N
    cov_x: np.ndarray        # parameter covariance (N, N)
    standardized: np.ndarray # standardized residuals (M,)


def solve_step(spec: AdjustmentSpec) -> AdjustmentResult:
    """Solve a single weighted-least-squares step.

    Uses the Cholesky factorisation of the normal equations
    ``N = A^T W A`` for speed and numerical stability.

    Parameters
    ----------
    spec
        Jacobian / discrepancy / weights.

    """
    a = np.asarray(spec.a, dtype=np.float64)
    l = np.asarray(spec.l, dtype=np.float64)
    w = np.asarray(spec.w, dtype=np.float64)
    if a.ndim != 2 or l.ndim != 1 or w.ndim != 1:
        raise ValueError("a must be 2-D, l and w must be 1-D.")
    m, n = a.shape
    if l.shape[0] != m or w.shape[0] != m:
        raise ValueError(f"Shape mismatch: a={a.shape}, l={l.shape}, w={w.shape}")
    if m < n:
        raise ValueError(f"System is under-determined: {m} obs < {n} params.")

    # Apply weights: scale rows of A and entries of l by sqrt(w).
    sqw = np.sqrt(w)
    a_w = a * sqw[:, None]
    l_w = l * sqw

    # Normal equations: N x = u, where N = A^T W A, u = A^T W l.
    nmat = a_w.T @ a_w
    u = a_w.T @ l_w

    # Cholesky factorisation. Falls back to pseudoinverse if the network
    # is rank-deficient (free / inner-constrained adjustments).
    try:
        c, low = la.cho_factor(nmat, lower=True, check_finite=False)
        x = la.cho_solve((c, low), u, check_finite=False)
        # Cov(x) = N^-1 (then scaled by sigma0^2 below)
        cov_x = la.cho_solve((c, low), np.eye(n), check_finite=False)
    except la.LinAlgError:
        # Rank-deficient / singular — use pseudoinverse for free adjustments.
        cov_x = la.pinv(nmat)
        x = cov_x @ u

    # Residuals v = A x - l.
    v = a @ x - l
    redundancy = m - n
    if redundancy <= 0:
        sigma0_sq = 0.0
    else:
        sigma0_sq = float((v.T @ (w * v)) / redundancy)

    cov_x_scaled = cov_x * (sigma0_sq if sigma0_sq > 0 else 1.0)

    # Standardized residuals (Pope's tau-test fodder).
    diag_qvv = 1.0 / w - np.einsum("ij,jk,ik->i", a, cov_x, a) / max(sigma0_sq, 1e-30)
    diag_qvv = np.clip(diag_qvv, 1e-30, None)
    standardized = v / np.sqrt(diag_qvv)

    return AdjustmentResult(
        x=x,
        v=v,
        sigma0_sq=sigma0_sq,
        redundancy=int(redundancy),
        cov_x=cov_x_scaled,
        standardized=standardized,
    )


def chi_square_test(sigma0_sq: float, redundancy: int, alpha: float = 0.05) -> bool:
    """Two-sided chi-square test on the reference variance.

    Returns ``True`` when the global test passes (i.e. the posterior
    σ₀² is consistent with the assumed σ₀² = 1).
    """
    if redundancy <= 0:
        return False
    try:
        from scipy.stats import chi2
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("scipy is required for chi_square_test") from e
    chi = sigma0_sq * redundancy
    lower = chi2.ppf(alpha / 2, redundancy)
    upper = chi2.ppf(1 - alpha / 2, redundancy)
    return bool(lower <= chi <= upper)


def error_ellipse_2d(cov_xy: np.ndarray, *, scale: float = 2.45) -> tuple[float, float, float]:
    """2-D error ellipse from a 2x2 covariance.

    Returns ``(a, b, theta)`` where ``a`` and ``b`` are the semi-axes and
    ``theta`` is the rotation of the ``a`` axis from the +x axis (radians).

    The default ``scale=2.45`` corresponds to a 95% confidence ellipse
    (chi² inverse for 2 degrees of freedom).
    """
    if cov_xy.shape != (2, 2):
        raise ValueError(f"Expected 2x2 covariance, got {cov_xy.shape}")
    # Eigendecomposition of the covariance.
    w, v = la.eigh(cov_xy)
    # eigh returns ascending eigenvalues — flip to put the largest first
    if w[0] > w[1]:
        w = w[::-1]
        v = v[:, ::-1]
    a = float(scale * math.sqrt(max(w[1], 0)))
    b = float(scale * math.sqrt(max(w[0], 0)))
    theta = float(math.atan2(v[1, 1], v[0, 1]))
    return a, b, theta


def detect_blunders(standardized: np.ndarray, *, threshold: float = 3.29) -> np.ndarray:
    """Return a boolean mask of suspected blunder observations.

    Default ``threshold=3.29`` matches a 99.9% test on the standardized
    residual (one-sided normal). Use ``2.58`` for 99% or ``1.96`` for 95%.
    """
    mask: np.ndarray = np.abs(standardized) > threshold
    return mask
