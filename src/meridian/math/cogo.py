"""Coordinate geometry — the daily bread of survey math.

All routines operate in a *plane* (a Cartesian projected CRS). For
geographic coordinates, transform first via :mod:`meridian.math.transforms`.

Conventions:

* Bearings / azimuths in **radians**, measured **clockwise from +y (north)**.
* Distances in **meters** (or whatever linear unit the CRS uses; routines
  are unit-agnostic but consistent).
* Coordinates as ``(x, y)`` tuples or numpy arrays of shape ``(N, 2)``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

TWO_PI = 2 * math.pi


# ── Bearing helpers ─────────────────────────────────────────────────────────


def normalize_bearing(b: float) -> float:
    """Normalize a bearing into [0, 2π)."""
    return b % TWO_PI


def back_bearing(b: float) -> float:
    """The 180-degree-reversed bearing."""
    return normalize_bearing(b + math.pi)


def bearing_difference(a: float, b: float) -> float:
    """Signed angle from ``a`` to ``b`` in (-π, π].

    Useful for closure / angular error calculations.
    """
    d = (b - a + math.pi) % TWO_PI - math.pi
    if d == -math.pi:
        return math.pi
    return d


# ── Inverse / forward ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InverseResult:
    """Result of an inverse computation between two points."""

    distance: float       # meters (or CRS unit)
    bearing: float        # radians, normalized to [0, 2π)


def inverse(p1: tuple[float, float], p2: tuple[float, float]) -> InverseResult:
    """Compute distance and bearing from p1 to p2 (planar)."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return InverseResult(distance=math.hypot(dx, dy), bearing=normalize_bearing(math.atan2(dx, dy)))


def forward(
    p: tuple[float, float],
    bearing: float,
    distance: float,
) -> tuple[float, float]:
    """Project a point along ``bearing`` for ``distance`` (planar)."""
    return (p[0] + distance * math.sin(bearing), p[1] + distance * math.cos(bearing))


def forward_array(
    p: tuple[float, float],
    bearings: np.ndarray,
    distances: np.ndarray,
) -> np.ndarray:
    """Vectorised forward — generates one point per (bearing, distance) pair.

    Returns array of shape ``(N, 2)``.
    """
    bearings = np.asarray(bearings, dtype=np.float64)
    distances = np.asarray(distances, dtype=np.float64)
    if bearings.shape != distances.shape:
        raise ValueError(f"Shape mismatch: {bearings.shape} vs {distances.shape}")
    xs = p[0] + distances * np.sin(bearings)
    ys = p[1] + distances * np.cos(bearings)
    return np.column_stack([xs, ys])


# ── Traverse ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TraverseResult:
    """Result of running a closed traverse."""

    coordinates: np.ndarray              # shape (N+1, 2): start + each leg's endpoint
    closure_distance: float
    closure_bearing: float
    closure_ratio: float                 # 1 / N
    perimeter: float
    area: float                          # signed (CCW positive)


def run_traverse(
    start: tuple[float, float],
    bearings: Sequence[float],
    distances: Sequence[float],
) -> TraverseResult:
    """Run a closed traverse and report closure.

    ``bearings`` and ``distances`` describe each leg in order; the result
    closes back to ``start`` and reports the misclosure vector.
    """
    if len(bearings) != len(distances):
        raise ValueError("bearings and distances must have the same length.")
    pts = [start]
    for b, d in zip(bearings, distances):
        pts.append(forward(pts[-1], b, d))
    coords = np.asarray(pts, dtype=np.float64)
    closure_dx = coords[-1, 0] - start[0]
    closure_dy = coords[-1, 1] - start[1]
    closure_dist = float(math.hypot(closure_dx, closure_dy))
    closure_brg = float(normalize_bearing(math.atan2(closure_dx, closure_dy)))
    perimeter = float(np.sum(np.asarray(distances, dtype=np.float64)))
    closure_ratio = float("inf") if closure_dist == 0 else perimeter / closure_dist
    # Signed area via shoelace on the closed polygon (drop duplicate end-vs-start
    # by treating the open list of N+1 coords as the polygon).
    area = _signed_shoelace(coords)
    return TraverseResult(
        coordinates=coords,
        closure_distance=closure_dist,
        closure_bearing=closure_brg,
        closure_ratio=closure_ratio,
        perimeter=perimeter,
        area=area,
    )


def _signed_shoelace(coords: np.ndarray) -> float:
    """Signed shoelace area of a closed polygon (first ≡ last allowed).

    Subtracts the centroid before summing so the formula doesn't lose
    precision when coordinates are large (a real concern in State Plane,
    where eastings can be 1e6 feet and the "area" terms are
    ``x_i * y_{i+1}`` of order 1e12). With centroid subtraction, terms
    are bounded by the polygon's diameter and the relative error stays
    near machine epsilon regardless of the absolute coordinate scale.
    """
    if coords.shape[0] < 3:
        return 0.0
    if not np.allclose(coords[0], coords[-1]):
        coords = np.vstack([coords, coords[0]])
    # Use the polygon's mean point as a local origin to keep terms small.
    cx = float(coords[:-1, 0].mean())
    cy = float(coords[:-1, 1].mean())
    x = coords[:, 0] - cx
    y = coords[:, 1] - cy
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


# ── Adjustment of an open traverse (Compass / Crandall / Transit) ───────────


def adjust_compass(
    bearings: Sequence[float],
    distances: Sequence[float],
    closure_dx: float,
    closure_dy: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compass-rule (Bowditch) adjustment.

    Distributes the closure error in proportion to leg distance. Returns
    ``(adjusted_dx, adjusted_dy)`` arrays of length ``N`` representing the
    corrected ΔX/ΔY for each leg. Reconstruct adjusted coordinates by
    cumulative sum from the start point.
    """
    bearings_arr = np.asarray(bearings, dtype=np.float64)
    distances_arr = np.asarray(distances, dtype=np.float64)
    if bearings_arr.shape != distances_arr.shape:
        raise ValueError("Shape mismatch.")
    perimeter = float(distances_arr.sum())
    if perimeter == 0:
        raise ValueError("Cannot adjust traverse with zero perimeter.")
    # Original ΔX/ΔY per leg
    dx = distances_arr * np.sin(bearings_arr)
    dy = distances_arr * np.cos(bearings_arr)
    # Distribute closure
    correction_x = -closure_dx * (distances_arr / perimeter)
    correction_y = -closure_dy * (distances_arr / perimeter)
    return dx + correction_x, dy + correction_y


def adjust_transit(
    bearings: Sequence[float],
    distances: Sequence[float],
    closure_dx: float,
    closure_dy: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Transit-rule adjustment.

    Distributes closure error in proportion to each leg's |ΔX| / sum|ΔX|
    and |ΔY| / sum|ΔY|. Use when angle measurements are believed more
    accurate than distance measurements (e.g. theodolite + EDM).
    """
    bearings_arr = np.asarray(bearings, dtype=np.float64)
    distances_arr = np.asarray(distances, dtype=np.float64)
    dx = distances_arr * np.sin(bearings_arr)
    dy = distances_arr * np.cos(bearings_arr)
    sum_abs_dx = float(np.abs(dx).sum())
    sum_abs_dy = float(np.abs(dy).sum())
    correction_x = (
        -closure_dx * (np.abs(dx) / sum_abs_dx) if sum_abs_dx > 0 else np.zeros_like(dx)
    )
    correction_y = (
        -closure_dy * (np.abs(dy) / sum_abs_dy) if sum_abs_dy > 0 else np.zeros_like(dy)
    )
    return dx + correction_x, dy + correction_y


# ── Area ────────────────────────────────────────────────────────────────────


def area_by_coordinates(coords: np.ndarray) -> float:
    """Absolute area by shoelace formula. Coords shape ``(N, 2)``."""
    return abs(_signed_shoelace(coords))


def area_by_dmd(bearings: Sequence[float], distances: Sequence[float]) -> float:
    """Area by Double Meridian Distance.

    Useful when only bearings + distances are known (no coordinates).
    Returns absolute area.
    """
    bearings_arr = np.asarray(bearings, dtype=np.float64)
    distances_arr = np.asarray(distances, dtype=np.float64)
    departures = distances_arr * np.sin(bearings_arr)   # ΔX
    latitudes = distances_arr * np.cos(bearings_arr)    # ΔY
    n = len(departures)
    dmd = np.zeros(n)
    dmd[0] = departures[0]
    for i in range(1, n):
        dmd[i] = dmd[i - 1] + departures[i - 1] + departures[i]
    return abs(float(0.5 * np.sum(dmd * latitudes)))


# ── Intersections ──────────────────────────────────────────────────────────


def intersect_bearing_bearing(
    p1: tuple[float, float],
    b1: float,
    p2: tuple[float, float],
    b2: float,
) -> tuple[float, float]:
    """Intersect two rays defined by point + bearing.

    Raises if the rays are parallel.
    """
    s1x, s1y = math.sin(b1), math.cos(b1)
    s2x, s2y = math.sin(b2), math.cos(b2)
    det = s1x * s2y - s1y * s2x
    if abs(det) < 1e-12:
        raise ValueError("Bearings are parallel — no intersection.")
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    t = (dx * s2y - dy * s2x) / det
    return (p1[0] + t * s1x, p1[1] + t * s1y)


def intersect_bearing_distance(
    p1: tuple[float, float],
    bearing: float,
    p2: tuple[float, float],
    distance: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Intersect a ray (p1, bearing) with a circle (center=p2, radius=distance).

    Returns the two intersection points (closest first along the ray).
    Raises if no intersection.
    """
    sx, sy = math.sin(bearing), math.cos(bearing)
    fx = p1[0] - p2[0]
    fy = p1[1] - p2[1]
    a = sx * sx + sy * sy        # = 1
    b = 2 * (fx * sx + fy * sy)
    c = fx * fx + fy * fy - distance * distance
    disc = b * b - 4 * a * c
    if disc < 0:
        raise ValueError("Ray does not intersect circle.")
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2 * a)
    t2 = (-b + sq) / (2 * a)
    return ((p1[0] + t1 * sx, p1[1] + t1 * sy), (p1[0] + t2 * sx, p1[1] + t2 * sy))


def intersect_distance_distance(
    p1: tuple[float, float],
    d1: float,
    p2: tuple[float, float],
    d2: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Intersect two circles. Returns both intersection points.

    Raises if circles do not intersect or are coincident.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    d = math.hypot(dx, dy)
    if d > d1 + d2 or d < abs(d1 - d2):
        raise ValueError("Circles do not intersect.")
    if d == 0 and d1 == d2:
        raise ValueError("Circles are coincident.")
    a = (d1 * d1 - d2 * d2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, d1 * d1 - a * a))
    px = p1[0] + a * dx / d
    py = p1[1] + a * dy / d
    return (
        (px + h * dy / d, py - h * dx / d),
        (px - h * dy / d, py + h * dx / d),
    )


# ── DMS conversion (helper for adapters) ────────────────────────────────────


def dms_to_radians(degrees: float, minutes: float, seconds: float, *, hemisphere: str | None = None) -> float:
    """Convert DMS to radians. Optional hemisphere ('S' or 'W' negate)."""
    angle = math.radians(abs(degrees) + abs(minutes) / 60 + abs(seconds) / 3600)
    if degrees < 0 or (hemisphere and hemisphere.upper() in ("S", "W")):
        angle = -angle
    return angle


def radians_to_dms(angle: float) -> tuple[int, int, float]:
    """Convert radians to (degrees, minutes, seconds)."""
    deg = math.degrees(angle)
    sign = 1 if deg >= 0 else -1
    deg_abs = abs(deg)
    d = int(deg_abs)
    rem = (deg_abs - d) * 60
    m = int(rem)
    s = (rem - m) * 60
    return (sign * d, m, s)


def quadrant_bearing(angle: float) -> tuple[str, int, int, float]:
    """Convert an azimuth (radians, clockwise from north) to a quadrant
    bearing as ``(NS, deg, min, sec, EW)`` — adapter-friendly.
    """
    az = normalize_bearing(angle)
    deg = math.degrees(az)
    if 0 <= deg <= 90:
        ns, ew = "N", "E"
        a = deg
    elif 90 < deg <= 180:
        ns, ew = "S", "E"
        a = 180 - deg
    elif 180 < deg <= 270:
        ns, ew = "S", "W"
        a = deg - 180
    else:
        ns, ew = "N", "W"
        a = 360 - deg
    d = int(a)
    rem = (a - d) * 60
    m = int(rem)
    s = (rem - m) * 60
    # We return NS as separate prefix for adapters; format string is theirs.
    return (ns + ew, d, m, s)
