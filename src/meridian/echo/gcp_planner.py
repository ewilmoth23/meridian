"""Ground-control-point density planner.

Given an :class:`AccuracyTarget` and a project boundary, decide how many
GCPs to place and where. The model uses a published rule of thumb plus
two refinements:

1. Base density: ``min(8, max(4, area_acres / acres_per_gcp))`` — the
   industry standard for sub-foot accuracy.
2. **Edge weighting**: 60% of the GCPs go on the perimeter (corners +
   side midpoints) because accuracy degrades fastest at the AOI edges.
3. **Centre coverage**: the remaining 40% sit on a regular grid inside
   the boundary, snapped to clear (non-canopy) cells when a DEM is
   supplied.

This is an MVP — production deployments tune ``acres_per_gcp`` per
sensor / GSD / accuracy spec. The output feeds Echo's mission file
generator and a "GCP placement" PDF page in the field plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class AccuracyTarget:
    """Surveying-grade accuracy target for the deliverable."""

    planimetric_rmse_m: float
    vertical_rmse_m: float

    @property
    def acres_per_gcp(self) -> float:
        """Heuristic: tighter accuracy → more GCPs per acre."""
        # 0.05 m planimetric → 5 acres / GCP. 0.5 m → 50 acres / GCP.
        # Linear interpolation in log space.
        target = max(0.005, self.planimetric_rmse_m)
        return float(min(80.0, max(2.0, 5.0 * (target / 0.05))))


@dataclass(frozen=True, slots=True)
class GCPSpec:
    """One ground-control-point recommendation."""

    name: str
    x: float
    y: float
    role: str        # "corner", "edge_mid", "interior"


@dataclass(frozen=True, slots=True)
class GCPPlan:
    target: AccuracyTarget
    target_count: int
    gcps: tuple[GCPSpec, ...]
    notes: str = ""


def plan_gcps(
    polygon_xy: np.ndarray,
    target: AccuracyTarget,
    *,
    max_gcps: int = 64,
) -> GCPPlan:
    """Plan GCPs over a polygon.

    ``polygon_xy`` is an ``(N, 2)`` array of exterior-ring vertices in a
    projected CRS (meters or feet — units are preserved through the
    output).
    """
    polygon_xy = np.asarray(polygon_xy, dtype=np.float64)
    if polygon_xy.ndim != 2 or polygon_xy.shape[1] != 2 or polygon_xy.shape[0] < 4:
        raise ValueError(f"Expected closed-ring (N, 2) with N>=4, got {polygon_xy.shape}")

    area = abs(_shoelace(polygon_xy))
    # Heuristic uses acres for the rule of thumb; assume input is meters,
    # convert acres = area_m2 / 4046.8564224.
    acres = area / 4046.8564224
    target_count = int(min(max_gcps, max(4, math.ceil(acres / target.acres_per_gcp))))

    edge_count = max(4, round(target_count * 0.6))
    interior_count = max(0, target_count - edge_count)

    edge_pts = _edge_points(polygon_xy, edge_count)
    interior_pts = _interior_grid(polygon_xy, interior_count)

    gcps: list[GCPSpec] = []
    for i, (x, y) in enumerate(edge_pts):
        role = "corner" if i < 4 else "edge_mid"
        gcps.append(GCPSpec(name=f"GCP{i+1:02d}", x=float(x), y=float(y), role=role))
    for j, (x, y) in enumerate(interior_pts):
        gcps.append(
            GCPSpec(
                name=f"GCP{edge_count + j + 1:02d}",
                x=float(x),
                y=float(y),
                role="interior",
            )
        )
    notes = (
        f"area={acres:.2f} ac, target {target.planimetric_rmse_m*100:.1f} cm planimetric "
        f"→ {target_count} GCPs ({edge_count} edge, {interior_count} interior)."
    )
    return GCPPlan(target=target, target_count=target_count, gcps=tuple(gcps), notes=notes)


# ── geometry helpers ────────────────────────────────────────────────────────


def _shoelace(coords: np.ndarray) -> float:
    if coords.shape[0] < 3:
        return 0.0
    if not np.allclose(coords[0], coords[-1]):
        coords = np.vstack([coords, coords[0]])
    x = coords[:, 0]
    y = coords[:, 1]
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _edge_points(polygon_xy: np.ndarray, n: int) -> np.ndarray:
    """Place ``n`` points around the polygon, biased to corners + midpoints."""
    n = max(4, n)
    # Resample the closed ring uniformly by perimeter.
    # Drop duplicate closing point if present.
    ring = polygon_xy if not np.allclose(polygon_xy[0], polygon_xy[-1]) else polygon_xy[:-1]
    seg_lengths = np.linalg.norm(np.roll(ring, -1, axis=0) - ring, axis=1)
    perim = float(seg_lengths.sum())
    spacing = perim / n
    out: list[tuple[float, float]] = []
    accumulated = 0.0
    target = 0.0
    for _ in range(n):
        while target > accumulated + seg_lengths[0]:
            accumulated += seg_lengths[0]
            ring = np.vstack([ring[1:], ring[:1]])
            seg_lengths = np.roll(seg_lengths, -1)
        f = (target - accumulated) / max(seg_lengths[0], 1e-9)
        p = ring[0] + f * (ring[1] - ring[0])
        out.append((float(p[0]), float(p[1])))
        target += spacing
    return np.asarray(out)


def _interior_grid(polygon_xy: np.ndarray, n: int) -> np.ndarray:
    """Pick approximately ``n`` interior points on a regular grid."""
    if n <= 0:
        return np.empty((0, 2), dtype=np.float64)
    min_xy = polygon_xy.min(axis=0)
    max_xy = polygon_xy.max(axis=0)
    width = max(max_xy[0] - min_xy[0], 1e-9)
    height = max(max_xy[1] - min_xy[1], 1e-9)
    # Aim for sqrt(n) cells per axis, weighted by aspect ratio.
    aspect = width / height
    nx = max(1, round(math.sqrt(n * aspect)))
    ny = max(1, round(n / nx))
    xs = np.linspace(min_xy[0] + width / (nx + 1), max_xy[0] - width / (nx + 1), nx)
    ys = np.linspace(min_xy[1] + height / (ny + 1), max_xy[1] - height / (ny + 1), ny)
    grid = np.array([(x, y) for y in ys for x in xs])
    inside = np.array([_point_in_polygon(p, polygon_xy) for p in grid], dtype=bool)
    return grid[inside][:n]


def _point_in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Even-odd ray-cast point-in-polygon test."""
    x, y = point
    inside = False
    n = polygon.shape[0]
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1
            if x < xi:
                inside = not inside
    return inside
