"""Statistical helpers for surveying.

Most of the heavy work in :mod:`meridian.math.adjustment` is itself
statistical; this module collects the smaller helpers used by reports
and quality checks.
"""

from __future__ import annotations

import math

import numpy as np


def rms(values: np.ndarray) -> float:
    """Root-mean-square of a 1-D array."""
    a = np.asarray(values, dtype=np.float64)
    return float(math.sqrt(np.mean(a * a))) if a.size else 0.0


def standard_deviation(values: np.ndarray, *, ddof: int = 1) -> float:
    """Sample standard deviation (Bessel-corrected by default)."""
    a = np.asarray(values, dtype=np.float64)
    if a.size <= ddof:
        return 0.0
    return float(np.std(a, ddof=ddof))


def mean_squared_error(observed: np.ndarray, predicted: np.ndarray) -> float:
    obs = np.asarray(observed, dtype=np.float64)
    pred = np.asarray(predicted, dtype=np.float64)
    if obs.shape != pred.shape:
        raise ValueError(f"Shape mismatch: {obs.shape} vs {pred.shape}")
    diff = obs - pred
    return float(np.mean(diff * diff))


def confidence_interval(values: np.ndarray, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided normal-approximation confidence interval on the mean."""
    a = np.asarray(values, dtype=np.float64)
    if a.size == 0:
        raise ValueError("Cannot compute CI on empty array.")
    from scipy.stats import norm

    mu = float(np.mean(a))
    se = float(np.std(a, ddof=1) / math.sqrt(a.size)) if a.size > 1 else 0.0
    z = float(norm.ppf(0.5 + confidence / 2))
    return mu - z * se, mu + z * se


def hausdorff_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric Hausdorff distance between two 2-D point sets.

    Returns the maximum of:
      * for every point in ``a``, the minimum distance to any point in ``b``
      * the symmetric counterpart

    Used for deed-vs-survey overlap analysis and boundary comparison.
    """
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    if aa.ndim != 2 or bb.ndim != 2 or aa.shape[1] != bb.shape[1]:
        raise ValueError(f"Shape mismatch: {aa.shape} vs {bb.shape}")
    from scipy.spatial.distance import cdist

    d = cdist(aa, bb)
    forward = float(d.min(axis=1).max()) if d.size else 0.0
    backward = float(d.min(axis=0).max()) if d.size else 0.0
    return max(forward, backward)


def closure_ratio(perimeter: float, misclosure: float) -> float:
    """Surveyor's closure ratio: ``perimeter / misclosure`` (a "1:N" number).

    Returns +infinity for zero misclosure.
    """
    if misclosure <= 0:
        return math.inf
    return perimeter / misclosure
