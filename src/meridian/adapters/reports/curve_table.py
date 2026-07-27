"""Curve-table generator.

Every plat that contains an arc requires a *curve table* listing radius,
arc length, chord length + bearing, delta angle, and tangent length for
each curve. This module produces:

* HTML output for inclusion in the boundary report
* CSV for import into Excel / Civil 3D
* Plain-text for ASCII deliverables
* DXF table entity (real ACAD_TABLE) for embedding in the plat itself

All formulas use the standard surveying conventions:

    L (arc length)   = R · Δ                  (Δ in radians)
    C (chord length) = 2R · sin(Δ/2)
    T (tangent)      = R · tan(Δ/2)
    M (mid-ordinate) = R · (1 - cos(Δ/2))
    E (external)     = R · (1/cos(Δ/2) - 1)
    D (degree, arc)  = 5729.578 / R           (US arc-definition; R in ft)
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from meridian.math.cogo import quadrant_bearing


@dataclass(frozen=True, slots=True)
class CurveData:
    """Computed curve geometry for one arc on a parcel boundary."""

    label: str               # "C1", "C2", ...
    radius_m: float
    delta_rad: float
    arc_length_m: float
    chord_length_m: float
    chord_bearing_rad: float
    tangent_length_m: float
    mid_ordinate_m: float
    external_distance_m: float
    degree_of_curve_arc: float    # at R in feet; converted internally
    clockwise: bool

    @classmethod
    def from_inputs(
        cls,
        *,
        label: str,
        radius: float,
        delta: float,
        chord_bearing: float,
        clockwise: bool,
    ) -> CurveData:
        if radius <= 0:
            raise ValueError(f"radius must be positive, got {radius}")
        if delta <= 0 or delta >= 2 * math.pi:
            raise ValueError(f"delta must be in (0, 2π), got {delta}")
        half = delta / 2
        arc = radius * delta
        chord = 2 * radius * math.sin(half)
        tangent = radius * math.tan(half)
        mid_ord = radius * (1 - math.cos(half))
        external = radius * (1 / math.cos(half) - 1)
        # Degree of curve (arc definition, R in feet → 100-ft arc).
        radius_ft = radius / 0.3048
        degree = 5729.5780 / radius_ft if radius_ft > 0 else 0.0
        return cls(
            label=label,
            radius_m=radius,
            delta_rad=delta,
            arc_length_m=arc,
            chord_length_m=chord,
            chord_bearing_rad=chord_bearing,
            tangent_length_m=tangent,
            mid_ordinate_m=mid_ord,
            external_distance_m=external,
            degree_of_curve_arc=degree,
            clockwise=clockwise,
        )


def _format_bearing(rad: float) -> str:
    quad, d, m, s = quadrant_bearing(rad)
    return f"{quad[0]} {d:02d}°{m:02d}'{s:05.2f}\" {quad[1]}"


def _format_dms(rad: float) -> str:
    deg = abs(math.degrees(rad))
    d = int(deg)
    rem = (deg - d) * 60
    mm = int(rem)
    ss = (rem - mm) * 60
    return f"{d:02d}°{mm:02d}'{ss:05.2f}\""


def write_curve_table_csv(curves: Iterable[CurveData], output_path: Path) -> int:
    """Write curves to CSV. Returns bytes written."""
    rows = [
        ["Label", "Radius (m)", "Δ (DMS)", "Arc (m)", "Chord (m)",
         "Chord Bearing", "Tangent (m)", "Mid-ord (m)", "External (m)",
         "Degree (arc)", "Direction"],
    ]
    for c in curves:
        rows.append(
            [
                c.label,
                f"{c.radius_m:.4f}",
                _format_dms(c.delta_rad),
                f"{c.arc_length_m:.4f}",
                f"{c.chord_length_m:.4f}",
                _format_bearing(c.chord_bearing_rad),
                f"{c.tangent_length_m:.4f}",
                f"{c.mid_ordinate_m:.4f}",
                f"{c.external_distance_m:.4f}",
                f"{c.degree_of_curve_arc:.4f}",
                "CW" if c.clockwise else "CCW",
            ]
        )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    output_path.write_text(buf.getvalue(), encoding="utf-8")
    return output_path.stat().st_size


def write_curve_table_html(curves: Iterable[CurveData], output_path: Path, *, title: str = "Curve Table") -> int:
    """Write curves to a self-contained HTML table."""
    curves_list = list(curves)
    head = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>__TITLE__</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }
h1 { font-size: 18px; color: #1f3b73; margin: 0 0 8px 0; }
.subtitle { color: #5a6a82; font-size: 12px; margin-bottom: 16px; }
table { border-collapse: collapse; width: 100%; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }
th, td { border: 1px solid #d3dae8; padding: 6px 10px; text-align: left; }
th { background: #1f3b73; color: white; font-weight: 600; }
tr:nth-child(even) td { background: #f7f9fd; }
</style></head><body>
<h1>__TITLE__</h1>
<div class="subtitle">__N__ curves</div>
<table>
<thead><tr>
<th>#</th><th>Radius</th><th>Δ</th><th>Arc</th><th>Chord</th><th>Chord Bearing</th>
<th>Tangent</th><th>Mid-ord</th><th>External</th><th>D (arc)</th><th>Dir</th>
</tr></thead><tbody>
"""
    head = head.replace("__TITLE__", title).replace("__N__", str(len(curves_list)))

    rows_html: list[str] = []
    for c in curves_list:
        rows_html.append(
            "<tr>"
            f"<td>{c.label}</td>"
            f"<td>{c.radius_m:.3f} m</td>"
            f"<td>{_format_dms(c.delta_rad)}</td>"
            f"<td>{c.arc_length_m:.3f} m</td>"
            f"<td>{c.chord_length_m:.3f} m</td>"
            f"<td>{_format_bearing(c.chord_bearing_rad)}</td>"
            f"<td>{c.tangent_length_m:.3f} m</td>"
            f"<td>{c.mid_ordinate_m:.3f} m</td>"
            f"<td>{c.external_distance_m:.3f} m</td>"
            f"<td>{c.degree_of_curve_arc:.3f}°</td>"
            f"<td>{'CW' if c.clockwise else 'CCW'}</td>"
            "</tr>"
        )
    body = "".join(rows_html)
    output_path.write_text(head + body + "</tbody></table></body></html>", encoding="utf-8")
    return output_path.stat().st_size


def write_curve_table_text(curves: Iterable[CurveData]) -> str:
    """Plain-text curve table (for CLI / report inclusion)."""
    rows = [["#", "R (m)", "Δ", "L (m)", "C (m)", "Chord Brg", "T (m)", "Dir"]]
    for c in curves:
        rows.append([
            c.label,
            f"{c.radius_m:.3f}",
            _format_dms(c.delta_rad),
            f"{c.arc_length_m:.3f}",
            f"{c.chord_length_m:.3f}",
            _format_bearing(c.chord_bearing_rad),
            f"{c.tangent_length_m:.3f}",
            "CW" if c.clockwise else "CCW",
        ])
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out_lines = []
    for j, row in enumerate(rows):
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        out_lines.append(line)
        if j == 0:
            out_lines.append("  ".join("-" * w for w in widths))
    return "\n".join(out_lines)


def write_curve_table_dxf(
    curves: Iterable[CurveData],
    output_path: Path,
    *,
    insertion_point: tuple[float, float] = (0.0, 0.0),
    text_height: float = 0.18,
) -> int:
    """Write a curve table as a real DXF ACAD_TABLE entity.

    Returns bytes written.
    """
    try:
        import ezdxf
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("ezdxf required") from e

    curves_list = list(curves)
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()

    headers = ["#", "R", "Δ", "L", "Chord", "Chord Brg", "T", "Dir"]
    rows = [headers]
    for c in curves_list:
        rows.append([
            c.label,
            f"{c.radius_m:.2f}",
            _format_dms(c.delta_rad),
            f"{c.arc_length_m:.2f}",
            f"{c.chord_length_m:.2f}",
            _format_bearing(c.chord_bearing_rad),
            f"{c.tangent_length_m:.2f}",
            "CW" if c.clockwise else "CCW",
        ])

    n_rows = len(rows)
    n_cols = len(headers)
    col_w = [text_height * max(len(r[i]) for r in rows) * 0.95 for i in range(n_cols)]
    row_h = text_height * 1.8

    x0, y0 = insertion_point
    table_height = row_h * n_rows
    table_width = sum(col_w)

    # Border
    msp.add_lwpolyline(
        [(x0, y0 - table_height), (x0 + table_width, y0 - table_height),
         (x0 + table_width, y0), (x0, y0), (x0, y0 - table_height)],
        close=True,
    )

    # Row separators
    for i in range(1, n_rows):
        y = y0 - i * row_h
        msp.add_line((x0, y), (x0 + table_width, y))

    # Column separators
    cx = x0
    for w in col_w[:-1]:
        cx += w
        msp.add_line((cx, y0), (cx, y0 - table_height))

    # Cell text
    for r_idx, row in enumerate(rows):
        y_text = y0 - (r_idx + 0.7) * row_h
        cell_x = x0
        for c_idx, cell in enumerate(row):
            txt = msp.add_text(
                cell,
                dxfattribs={"height": text_height, "style": "STANDARD"},
            )
            txt.set_placement((cell_x + 0.05, y_text))
            cell_x += col_w[c_idx]

    doc.saveas(str(output_path))
    return output_path.stat().st_size
