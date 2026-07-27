"""DXF exporter — built on :mod:`ezdxf`.

Replaces the prototype's three-version, ASCII-handcoded DXF writer with a
single ezdxf-based implementation that handles R2018+ binary/ASCII,
proper layers, blocks, linetypes, and annotations.

The exporter generates a deliverable-grade DXF for a single :class:`Survey`
or :class:`Parcel`, with these layers (configurable via options):

* ``BOUNDARY`` — parcel exterior, by-layer color cyan.
* ``BOUNDARY-INTERIOR`` — parcel holes.
* ``MONUMENTS`` — point monuments as inserted blocks.
* ``LABELS-BEARING-DIST`` — bearing/distance line labels.
* ``LABELS-PARCEL`` — parcel name and area.
* ``CONTROL-POINTS`` — adjusted network points.
* ``ERROR-ELLIPSES`` — 95% confidence ellipses.
* ``CONTOURS`` — point-cloud-derived contour lines.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget

if TYPE_CHECKING:
    from meridian.domain.geometry import Point2D
    from meridian.domain.parcel import Parcel
    from meridian.domain.survey import Survey


# Default layer / color scheme.
DEFAULT_LAYERS: dict[str, dict[str, object]] = {
    "BOUNDARY":              {"color": 4, "linetype": "CONTINUOUS", "lineweight": 50},
    "BOUNDARY-INTERIOR":     {"color": 4, "linetype": "DASHED",     "lineweight": 35},
    "MONUMENTS":             {"color": 1, "linetype": "CONTINUOUS"},
    "LABELS-BEARING-DIST":   {"color": 7, "linetype": "CONTINUOUS"},
    "LABELS-PARCEL":         {"color": 7, "linetype": "CONTINUOUS"},
    "CONTROL-POINTS":        {"color": 2, "linetype": "CONTINUOUS"},
    "ERROR-ELLIPSES":        {"color": 6, "linetype": "DASHED"},
    "CONTOURS":              {"color": 8, "linetype": "CONTINUOUS"},
    "CONTOURS-INDEX":        {"color": 3, "linetype": "CONTINUOUS", "lineweight": 35},
    "TIN-EDGES":             {"color": 250, "linetype": "CONTINUOUS"},
}


class DXFExporter(Exporter):
    """ezdxf-based DXF exporter."""

    name = "DXF (R2018)"
    short_id = "dxf"
    extensions = ("dxf",)
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        try:
            import ezdxf
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "DXFExporter requires ezdxf. Install with: pip install ezdxf"
            ) from e

        dxf_version = str(options.get("dxf_version", "R2018"))
        units_label = str(options.get("units", survey.crs.units.value))
        annotations = bool(options.get("annotations", True))

        doc = ezdxf.new(dxf_version, setup=True)

        # Set drawing units. ezdxf's INSUNITS values: 1=in, 2=ft, 6=m
        units_code = {"m": 6, "ft": 2, "us_ft": 2, "ift": 2}.get(units_label, 0)
        doc.header["$INSUNITS"] = units_code

        # Linetypes (ezdxf creates CONTINUOUS by default; add DASHED if missing)
        if "DASHED" not in doc.linetypes:
            doc.linetypes.add(
                name="DASHED",
                pattern="A,1,-0.5",
                description="Dashed __ __ __ __ __ __",
            )

        # Layers
        for name, props in DEFAULT_LAYERS.items():
            if name in doc.layers:
                continue
            layer = doc.layers.add(name)
            if "color" in props:
                layer.color = int(props["color"])  # type: ignore[arg-type]
            if "linetype" in props and props["linetype"] in doc.linetypes:
                layer.dxf.linetype = str(props["linetype"])
            if "lineweight" in props:
                layer.dxf.lineweight = int(props["lineweight"])  # type: ignore[arg-type]

        msp = doc.modelspace()

        # Draw parcels
        for parcel in survey.parcels:
            self._draw_parcel(msp, parcel, annotate=annotations)

        # Draw control points
        for adj in survey.adjustments:
            self._draw_adjustment(msp, adj)

        doc.saveas(str(output_path))

        bytes_written = output_path.stat().st_size if output_path.exists() else 0
        return ExportResult(
            output_path=output_path,
            bytes_written=bytes_written,
            metadata={"dxf_version": dxf_version, "units": units_label},
        )

    # ── private drawing helpers ─────────────────────────────────────────────

    def _draw_parcel(self, msp: object, parcel: Parcel, *, annotate: bool) -> None:
        if parcel.boundary is None:
            return
        polygon = parcel.boundary.polygon
        coords = [(p.x, p.y) for p in polygon.exterior]
        msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": "BOUNDARY"})  # type: ignore[attr-defined]
        for hole in polygon.holes:
            hole_coords = [(p.x, p.y) for p in hole]
            msp.add_lwpolyline(hole_coords, close=True, dxfattribs={"layer": "BOUNDARY-INTERIOR"})  # type: ignore[attr-defined]

        # POB monument
        pob = parcel.boundary.point_of_beginning
        msp.add_circle(  # type: ignore[attr-defined]
            (pob.x, pob.y),
            radius=parcel.boundary.perimeter * 0.005 + 0.5,
            dxfattribs={"layer": "MONUMENTS"},
        )
        msp.add_text(  # type: ignore[attr-defined]
            "POB",
            dxfattribs={"layer": "MONUMENTS", "height": parcel.boundary.perimeter * 0.01 + 1},
        ).set_placement((pob.x, pob.y))

        if annotate:
            self._annotate_parcel(msp, parcel)

    def _annotate_parcel(self, msp: object, parcel: Parcel) -> None:
        """Place bearing/distance labels at each line midpoint."""
        if parcel.boundary is None:
            return
        polygon = parcel.boundary.polygon
        ext = polygon.exterior
        text_height = parcel.boundary.perimeter * 0.005 + 0.6
        for i, c in enumerate(parcel.calls):
            if c.bearing is None or c.distance is None:
                continue
            try:
                p1: Point2D = ext[i]
                p2: Point2D = ext[i + 1]
            except IndexError:
                break
            mx, my = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
            label = f"{_format_bearing(c.bearing)}  {c.distance:,.2f} m"
            txt = msp.add_text(  # type: ignore[attr-defined]
                label,
                dxfattribs={"layer": "LABELS-BEARING-DIST", "height": text_height},
            )
            # Rotate label parallel to the line.
            angle = math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))
            txt.dxf.rotation = angle
            txt.set_placement((mx, my))

        # Parcel name + area centroid label
        area = polygon.area()
        cx = sum(p.x for p in ext[:-1]) / (len(ext) - 1)
        cy = sum(p.y for p in ext[:-1]) / (len(ext) - 1)
        msp.add_text(  # type: ignore[attr-defined]
            f"{parcel.name}\n{area:,.2f} m²  ({area / 4046.8564224:,.4f} ac)",
            dxfattribs={
                "layer": "LABELS-PARCEL",
                "height": text_height * 1.3,
                "style": "STANDARD",
            },
        ).set_placement((cx, cy))

    def _draw_adjustment(self, msp: object, adj: object) -> None:
        for pid, p in adj.adjusted_points.items():  # type: ignore[attr-defined]
            msp.add_circle((p.x, p.y), radius=1.0, dxfattribs={"layer": "CONTROL-POINTS"})  # type: ignore[attr-defined]
            msp.add_text(  # type: ignore[attr-defined]
                pid,
                dxfattribs={"layer": "CONTROL-POINTS", "height": 0.8},
            ).set_placement((p.x + 1.5, p.y + 1.5))
        for pid, ell in adj.error_ellipses.items():  # type: ignore[attr-defined]
            p = adj.adjusted_points[pid]  # type: ignore[attr-defined]
            self._draw_ellipse(msp, (p.x, p.y), ell.a, ell.b, ell.theta)

    def _draw_ellipse(self, msp: object, center: tuple[float, float], a: float, b: float, theta: float) -> None:
        # ezdxf ELLIPSE entity needs major axis vector + ratio
        major_x = a * math.cos(theta)
        major_y = a * math.sin(theta)
        ratio = b / a if a > 0 else 1.0
        msp.add_ellipse(  # type: ignore[attr-defined]
            center=center,
            major_axis=(major_x, major_y),
            ratio=ratio,
            dxfattribs={"layer": "ERROR-ELLIPSES"},
        )


def _format_bearing(azimuth: float) -> str:
    """Quadrant bearing label like ``N 45°30'15" E``."""
    from meridian.math.cogo import quadrant_bearing

    quad, d, m, s = quadrant_bearing(azimuth)
    ns, ew = quad[0], quad[1]
    return f"{ns} {d}°{m:02d}'{s:05.2f}\" {ew}"
