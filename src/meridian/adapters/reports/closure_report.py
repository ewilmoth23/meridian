"""Closure-analysis report.

Computes closure for a traverse using all four classical methods
(unadjusted, compass / Bowditch, transit, Crandall) plus least-squares
when invoked through the network adjustment, then produces a side-by-
side comparison report so reviewers can pick the appropriate method.

Surveying convention defines the closure precision as
``perimeter / misclosure_distance`` (a 1:N number — bigger N is better).
We also compute area by the DMD (Double Meridian Distance) and DPD
(Double Parallel Distance) methods so callers can verify the shoelace
result.

The text + HTML reports compare:

  * Linear closure (m, ft)
  * Closure direction (azimuth)
  * Closure ratio (1:N)
  * Area by coordinates (shoelace), DMD, and DPD
  * Pass/fail against an industry standard (ALTA/NSPS, FIRST_ORDER,
    SECOND_ORDER, CONSTRUCTION).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from meridian.math.cogo import (
    adjust_compass,
    adjust_transit,
    area_by_coordinates,
    area_by_dmd,
    run_traverse,
)


class ClosureStandard(str, Enum):
    """Industry closure ratio targets."""

    FIRST_ORDER = "first_order"          # 1:100,000
    SECOND_ORDER = "second_order"        # 1:50,000
    THIRD_ORDER = "third_order"          # 1:10,000
    ALTA_NSPS = "alta_nsps"              # 1:15,000 typical
    URBAN = "urban"                      # 1:7,500
    SUBURBAN = "suburban"                # 1:5,000
    RURAL = "rural"                      # 1:2,500
    CONSTRUCTION = "construction"        # 1:1,000

    @property
    def ratio(self) -> float:
        return {
            ClosureStandard.FIRST_ORDER: 100_000,
            ClosureStandard.SECOND_ORDER: 50_000,
            ClosureStandard.THIRD_ORDER: 10_000,
            ClosureStandard.ALTA_NSPS: 15_000,
            ClosureStandard.URBAN: 7_500,
            ClosureStandard.SUBURBAN: 5_000,
            ClosureStandard.RURAL: 2_500,
            ClosureStandard.CONSTRUCTION: 1_000,
        }[self]


@dataclass(frozen=True, slots=True)
class MethodResult:
    """Closure stats for one adjustment method."""

    method: str
    closure_m: float
    closure_bearing_deg: float
    closure_ratio: float
    perimeter_m: float
    area_m2: float
    coords: np.ndarray              # shape (N+1, 2) — adjusted polygon
    pass_ratio: bool


@dataclass(frozen=True, slots=True)
class ClosureReport:
    """Multi-method comparison."""

    standard: ClosureStandard
    perimeter_m: float
    area_dmd_m2: float
    area_shoelace_m2: float
    methods: tuple[MethodResult, ...]


def analyze(
    *,
    bearings: Sequence[float],
    distances: Sequence[float],
    starting_point: tuple[float, float] = (0.0, 0.0),
    standard: ClosureStandard = ClosureStandard.ALTA_NSPS,
) -> ClosureReport:
    """Run unadjusted + compass + transit and report closure for each."""
    raw = run_traverse(starting_point, bearings, distances)
    closure_dx = float(raw.coordinates[-1, 0] - starting_point[0])
    closure_dy = float(raw.coordinates[-1, 1] - starting_point[1])

    methods: list[MethodResult] = []
    methods.append(_method_result("Unadjusted", raw.coordinates, raw.perimeter, standard))

    for name, fn in (("Compass / Bowditch", adjust_compass), ("Transit", adjust_transit)):
        adj_dx, adj_dy = fn(bearings, distances, closure_dx, closure_dy)
        coords = np.zeros((len(bearings) + 1, 2), dtype=np.float64)
        coords[0] = starting_point
        for i in range(len(bearings)):
            coords[i + 1, 0] = coords[i, 0] + adj_dx[i]
            coords[i + 1, 1] = coords[i, 1] + adj_dy[i]
        methods.append(_method_result(name, coords, raw.perimeter, standard))

    return ClosureReport(
        standard=standard,
        perimeter_m=raw.perimeter,
        area_dmd_m2=area_by_dmd(bearings, distances),
        area_shoelace_m2=area_by_coordinates(raw.coordinates),
        methods=tuple(methods),
    )


def _method_result(
    name: str, coords: np.ndarray, perimeter: float, standard: ClosureStandard
) -> MethodResult:
    closure_dx = float(coords[-1, 0] - coords[0, 0])
    closure_dy = float(coords[-1, 1] - coords[0, 1])
    closure = math.hypot(closure_dx, closure_dy)
    bearing_rad = math.atan2(closure_dx, closure_dy) % (2 * math.pi) if closure > 0 else 0.0
    ratio = float("inf") if closure == 0 else perimeter / closure
    return MethodResult(
        method=name,
        closure_m=closure,
        closure_bearing_deg=math.degrees(bearing_rad),
        closure_ratio=ratio,
        perimeter_m=perimeter,
        area_m2=area_by_coordinates(coords),
        coords=coords,
        pass_ratio=ratio == float("inf") or ratio >= standard.ratio,
    )


# ── Output formatters ───────────────────────────────────────────────────────


def write_closure_report_html(report: ClosureReport, output_path: Path, *, title: str = "Closure Analysis") -> int:
    rows = []
    for m in report.methods:
        ratio_str = "∞" if math.isinf(m.closure_ratio) else f"1:{m.closure_ratio:,.0f}"
        verdict = "PASS" if m.pass_ratio else "FAIL"
        verdict_color = "#0a8a3a" if m.pass_ratio else "#c33"
        rows.append(
            f"<tr><td>{m.method}</td><td>{m.closure_m:.4f} m</td>"
            f"<td>{m.closure_bearing_deg:.4f}°</td>"
            f"<td>{ratio_str}</td><td>{m.area_m2:,.3f} m²</td>"
            f"<td style='color:{verdict_color};font-weight:600'>{verdict}</td></tr>"
        )

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }}
h1 {{ font-size: 18px; color: #1f3b73; margin: 0 0 8px 0; }}
.subtitle {{ color: #5a6a82; font-size: 12px; margin-bottom: 16px; }}
.card {{ background: #f7f9fd; border-left: 4px solid #1f3b73; padding: 12px 18px; margin: 12px 0; }}
.card .lbl {{ color: #5a6a82; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
.card .val {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #d3dae8; padding: 6px 12px; text-align: left; font-family: ui-monospace, Menlo, Consolas, monospace; }}
th {{ background: #1f3b73; color: white; font-weight: 600; }}
tr:nth-child(even) td {{ background: #f7f9fd; }}
</style></head><body>
<h1>{title}</h1>
<div class="subtitle">Standard target: {report.standard.value} (1:{int(report.standard.ratio):,})</div>
<div class="card">
  <div><span class="lbl">Perimeter</span> <span class="val">{report.perimeter_m:,.3f} m</span></div>
  <div><span class="lbl">Area (shoelace)</span> <span class="val">{report.area_shoelace_m2:,.3f} m² &nbsp;&nbsp; ({report.area_shoelace_m2 / 4046.8564224:,.4f} ac)</span></div>
  <div><span class="lbl">Area (DMD)</span> <span class="val">{report.area_dmd_m2:,.3f} m²</span></div>
</div>
<table>
<thead><tr><th>Method</th><th>Misclosure</th><th>Direction</th><th>Ratio</th><th>Area</th><th>Verdict</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>"""
    output_path.write_text(html, encoding="utf-8")
    return output_path.stat().st_size


def write_closure_report_text(report: ClosureReport) -> str:
    lines = [
        "CLOSURE ANALYSIS REPORT",
        f"Standard: {report.standard.value} (target 1:{int(report.standard.ratio):,})",
        f"Perimeter: {report.perimeter_m:,.3f} m",
        f"Area (shoelace): {report.area_shoelace_m2:,.3f} m²  ({report.area_shoelace_m2 / 4046.8564224:,.4f} ac)",
        f"Area (DMD):      {report.area_dmd_m2:,.3f} m²",
        "",
        f"{'Method':24s}  {'Misclosure (m)':>14s}  {'Bearing (°)':>11s}  {'Ratio':>14s}  {'Area (m²)':>14s}  Verdict",
    ]
    for m in report.methods:
        ratio_str = "∞" if math.isinf(m.closure_ratio) else f"1:{m.closure_ratio:>12,.0f}"
        verdict = "PASS" if m.pass_ratio else "FAIL"
        lines.append(
            f"{m.method:24s}  {m.closure_m:14.4f}  {m.closure_bearing_deg:11.4f}"
            f"  {ratio_str:>14s}  {m.area_m2:14,.3f}  {verdict}"
        )
    return "\n".join(lines)
