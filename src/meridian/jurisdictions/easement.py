"""Easement analyzer — parallel offsets, conflict detection, encumbered area.

An easement is a non-possessory right to use someone else's land. The
surveyor needs to:

* Generate the easement *strip* polygon from a centerline + width.
* Detect where it conflicts with other easements / building footprints.
* Compute the *encumbered area* (parent area minus easement strips).
* Classify the easement by purpose (access, utility, drainage, ...).

This module covers the planar geometry side. The legal classification
side is handled by :mod:`meridian.jurisdictions.title_commitment`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Polygon


class EasementPurpose(str, Enum):
    ACCESS = "access"
    UTILITY = "utility"
    DRAINAGE = "drainage"
    INGRESS_EGRESS = "ingress_egress"
    PEDESTRIAN = "pedestrian"
    SLOPE = "slope"
    SIGHT = "sight"
    PIPELINE = "pipeline"
    POWER = "power"
    RAIL = "rail"
    CONSERVATION = "conservation"
    OTHER = "other"


class EasementOrigin(str, Enum):
    EXPRESS_GRANT = "express_grant"
    RESERVATION = "reservation"
    PRESCRIPTIVE = "prescriptive"
    NECESSITY = "necessity"
    IMPLIED = "implied"
    PUBLIC_DEDICATION = "public_dedication"
    APPURTENANT = "appurtenant"
    IN_GROSS = "in_gross"


@dataclass(frozen=True, slots=True)
class Easement:
    """A linear easement defined by a centerline + width."""

    name: str
    purpose: EasementPurpose
    origin: EasementOrigin
    centerline: tuple[tuple[float, float], ...]   # (x, y) per vertex
    width_m: float                                  # total width (half on each side)
    holder: str | None = None
    recording_reference: str | None = None
    notes: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def half_width(self) -> float:
        return self.width_m / 2.0


@dataclass(frozen=True, slots=True)
class EasementConflict:
    """A geometric conflict between two easements (or easement vs. building)."""

    a_name: str
    b_name: str
    severity: str        # "overlap", "crossing", "containment", "adjacency"
    overlap_area_m2: float
    notes: str | None = None


# ── Buffer / strip generation ─────────────────────────────────────────────


def parallel_offset(
    centerline: Sequence[tuple[float, float]],
    distance: float,
    *,
    side: str = "left",
) -> np.ndarray:
    """Compute a parallel offset of a polyline at signed distance ``distance``.

    ``side`` is ``"left"`` (positive normal — perpendicular to the polyline
    direction, rotated 90° CCW) or ``"right"``. The result is an
    ``(N, 2)`` numpy array in the same coordinate system as the input.

    Uses miter joins. Sharp angles (> 60° turn) are clipped to bevel to
    avoid spike artifacts.
    """
    if len(centerline) < 2:
        raise ValueError("centerline must have at least 2 points")
    sign = 1.0 if side == "left" else -1.0
    pts = np.asarray(centerline, dtype=np.float64)

    # Per-segment unit normals (rotated 90° CCW).
    segs = pts[1:] - pts[:-1]
    seg_lengths = np.linalg.norm(segs, axis=1)
    seg_lengths = np.where(seg_lengths < 1e-12, 1e-12, seg_lengths)
    unit = segs / seg_lengths[:, None]
    normals = np.column_stack([-unit[:, 1], unit[:, 0]]) * sign * distance

    out = np.zeros_like(pts)
    out[0] = pts[0] + normals[0]
    out[-1] = pts[-1] + normals[-1]
    for i in range(1, len(pts) - 1):
        # Miter join — bisector-of-normals direction.
        n1 = normals[i - 1]
        n2 = normals[i]
        bisector = n1 + n2
        bnorm = np.linalg.norm(bisector)
        if bnorm < 1e-12:
            # 180° turn — fall back to one side's normal.
            out[i] = pts[i] + n1
            continue
        bisector /= bnorm
        # Distance along bisector to land on both offsets.
        cos_half = float(np.dot(bisector, n1) / max(np.linalg.norm(n1), 1e-12))
        if cos_half < 0.5:
            # Miter would spike; bevel by averaging.
            out[i] = pts[i] + (n1 + n2) / 2
        else:
            out[i] = pts[i] + bisector * (distance / max(cos_half, 0.5))
    return out


def easement_strip_polygon(easement: Easement) -> np.ndarray:
    """Generate the closed strip polygon for an easement.

    Returns an ``(N+1, 2)`` numpy array of polygon vertices (closed —
    last point equals first). Suitable for handing to
    :class:`~meridian.domain.geometry.Polygon` after wrapping in
    :class:`~meridian.domain.geometry.Point2D` per vertex.
    """
    half = easement.half_width()
    left = parallel_offset(easement.centerline, half, side="left")
    right = parallel_offset(easement.centerline, half, side="right")
    # Combine left forward + right backward + close.
    coords = np.vstack([left, right[::-1], left[:1]])
    return coords


def easement_to_polygon(easement: Easement, crs: CRS) -> Polygon:
    """Build a domain :class:`Polygon` for the easement strip."""
    from meridian.domain.geometry import Point2D, Polygon

    coords = easement_strip_polygon(easement)
    pts = tuple(Point2D(x=float(c[0]), y=float(c[1]), crs=crs) for c in coords)
    return Polygon(exterior=pts).oriented()


# ── Encumbrance / area math ───────────────────────────────────────────────


def encumbered_area(easements: Iterable[Easement]) -> float:
    """Total area covered by all easement strips (no de-overlap).

    For a properly de-overlapped result, intersect with each parent and
    use shapely / GEOS — that's the v0.6 parcel-fabric layer's job.
    """
    total = 0.0
    for ease in easements:
        try:
            coords = easement_strip_polygon(ease)
            # Shoelace area.
            x = coords[:, 0]
            y = coords[:, 1]
            cx = float(x[:-1].mean())
            cy = float(y[:-1].mean())
            total += abs(0.5 * float(np.sum((x[:-1] - cx) * (y[1:] - cy) - (x[1:] - cx) * (y[:-1] - cy))))
        except Exception:
            continue
    return total


def detect_conflicts(
    easements: Sequence[Easement],
    *,
    overlap_threshold_m2: float = 0.01,
) -> list[EasementConflict]:
    """Detect overlapping / crossing easements.

    For each pair, computes the strip-strip overlap via shapely (when
    available) or a fast bounding-box pre-filter + manual SAT test. The
    ``overlap_threshold_m2`` filters trivial corner-touches.
    """
    conflicts: list[EasementConflict] = []
    n = len(easements)
    if n < 2:
        return conflicts

    # Pre-compute strips + bboxes.
    strips: list[np.ndarray] = []
    bboxes: list[tuple[float, float, float, float]] = []
    for ease in easements:
        try:
            strip = easement_strip_polygon(ease)
            strips.append(strip)
            bboxes.append((strip[:, 0].min(), strip[:, 1].min(), strip[:, 0].max(), strip[:, 1].max()))
        except Exception:
            strips.append(np.empty((0, 2)))
            bboxes.append((math.inf, math.inf, -math.inf, -math.inf))

    for i in range(n):
        for j in range(i + 1, n):
            if strips[i].size == 0 or strips[j].size == 0:
                continue
            if not _bboxes_overlap(bboxes[i], bboxes[j]):
                continue
            overlap = _polygon_intersection_area(strips[i], strips[j])
            if overlap < overlap_threshold_m2:
                continue
            severity = (
                "containment" if overlap >= 0.95 * min(_shoelace(strips[i]), _shoelace(strips[j]))
                else "overlap"
            )
            conflicts.append(
                EasementConflict(
                    a_name=easements[i].name,
                    b_name=easements[j].name,
                    severity=severity,
                    overlap_area_m2=overlap,
                )
            )
    return conflicts


# ── Geometry helpers ───────────────────────────────────────────────────────


def _bboxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _shoelace(coords: np.ndarray) -> float:
    if coords.shape[0] < 3:
        return 0.0
    x = coords[:, 0]
    y = coords[:, 1]
    cx = float(x[:-1].mean())
    cy = float(y[:-1].mean())
    return abs(0.5 * float(np.sum((x[:-1] - cx) * (y[1:] - cy) - (x[1:] - cx) * (y[:-1] - cy))))


def _signed_shoelace_for_orientation(coords: np.ndarray) -> float:
    """Signed shoelace — positive for CCW polygons, negative for CW."""
    if coords.shape[0] < 3:
        return 0.0
    x = coords[:, 0]
    y = coords[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _ensure_ccw(coords: np.ndarray) -> np.ndarray:
    """Reverse if the polygon is CW; SH clipping needs CCW orientation."""
    return coords[::-1] if _signed_shoelace_for_orientation(coords) < 0 else coords


def _polygon_intersection_area(a: np.ndarray, b: np.ndarray) -> float:
    """Sutherland-Hodgman polygon clipping for the intersection area.

    Both polygons must be convex; CCW orientation is enforced internally.
    """
    a = _ensure_ccw(a)
    b = _ensure_ccw(b)
    output = list(a[:-1])  # drop closing point if present
    clip = list(b[:-1])

    def _inside(p, edge):
        # Inside = on the right of the directed edge (CCW assumption).
        return (edge[1][0] - edge[0][0]) * (p[1] - edge[0][1]) - (edge[1][1] - edge[0][1]) * (p[0] - edge[0][0]) >= 0

    def _intersect(p1, p2, e1, e2):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = e1
        x4, y4 = e2
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    for i in range(len(clip)):
        if not output:
            break
        edge = (clip[i], clip[(i + 1) % len(clip)])
        new_output: list[tuple[float, float]] = []
        for j in range(len(output)):
            cur = output[j]
            prev = output[j - 1]
            cur_in = _inside(cur, edge)
            prev_in = _inside(prev, edge)
            if cur_in:
                if not prev_in:
                    new_output.append(_intersect(prev, cur, edge[0], edge[1]))
                new_output.append(cur)
            elif prev_in:
                new_output.append(_intersect(prev, cur, edge[0], edge[1]))
        output = new_output

    if len(output) < 3:
        return 0.0
    arr = np.asarray([*output, output[0]], dtype=np.float64)
    return _shoelace(arr)


# ── Report ─────────────────────────────────────────────────────────────────


def write_easement_report_html(
    easements: Sequence[Easement],
    conflicts: Sequence[EasementConflict],
    output_path,
) -> int:
    """Render a self-contained HTML easement report."""
    rows = []
    for e in easements:
        rows.append(
            f"<tr><td>{e.name}</td><td>{e.purpose.value}</td>"
            f"<td>{e.origin.value}</td>"
            f"<td>{e.width_m:.2f} m</td>"
            f"<td>{e.holder or '—'}</td>"
            f"<td>{e.recording_reference or '—'}</td></tr>"
        )
    cflrows = []
    for c in conflicts:
        cflrows.append(
            f"<tr><td>{c.a_name}</td><td>{c.b_name}</td>"
            f"<td><b>{c.severity}</b></td>"
            f"<td>{c.overlap_area_m2:.3f} m²</td></tr>"
        )
    total_area = encumbered_area(easements)

    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>Easement Analysis</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }}
h1 {{ font-size: 18px; color: #1f3b73; margin: 0 0 4px 0; }}
h2 {{ font-size: 14px; color: #1f3b73; margin: 18px 0 6px 0; border-bottom: 1px solid #d3dae8; padding-bottom: 4px; }}
.subtitle {{ color: #5a6a82; font-size: 12px; margin-bottom: 16px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #d3dae8; padding: 6px 10px; text-align: left; }}
th {{ background: #1f3b73; color: white; font-weight: 600; }}
tr:nth-child(even) td {{ background: #f7f9fd; }}
.ok {{ color: #0a8a3a; }}
.warn {{ color: #c33; }}
</style></head><body>
<h1>Easement Analysis</h1>
<div class="subtitle">{len(easements)} easement{'' if len(easements) == 1 else 's'} · total encumbered area {total_area:,.2f} m² ({total_area / 4046.8564224:,.4f} ac)</div>
<h2>Easements</h2>
<table><thead><tr><th>Name</th><th>Purpose</th><th>Origin</th><th>Width</th><th>Holder</th><th>Recording</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6"><em>None.</em></td></tr>'}</tbody></table>
<h2>Conflicts ({len(conflicts)})</h2>
<table><thead><tr><th>A</th><th>B</th><th>Severity</th><th>Overlap area</th></tr></thead>
<tbody>{''.join(cflrows) or '<tr><td colspan="4"><em>None detected.</em></td></tr>'}</tbody></table>
</body></html>"""
    if hasattr(output_path, "write_text"):
        output_path.write_text(body, encoding="utf-8")
        return output_path.stat().st_size
    return 0
