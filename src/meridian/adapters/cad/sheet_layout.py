"""Sheet-layout generator — title block, scale bar, north arrow, legend.

A sheet layout decorates a parcel-or-survey DXF with the deliverable
furniture surveyors expect: a paper-size border, a title block in the
lower-right corner, a graphic scale bar, a north arrow, and a layer
legend. Everything is drawn in *paperspace* (DXF "Layout1"), with the
plan view at a chosen scale on the same sheet.

Supported page sizes: ANSI A through E, ARCH A through E1, ISO A4 through
A0. Units in points (1/72 inch) internally; all DXF output is in the
sheet's chosen unit (inch or millimeter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from meridian.adapters.cad.layer_config import (
    DEFAULT_PRESET,
    LayerPreset,
    SemanticLayer,
)

if TYPE_CHECKING:
    from meridian.domain.parcel import Parcel


class PageUnit(str, Enum):
    INCH = "in"
    MILLIMETER = "mm"


@dataclass(frozen=True, slots=True)
class PageSize:
    """A sheet size definition."""

    name: str
    width: float
    height: float
    unit: PageUnit

    def landscape(self) -> PageSize:
        return PageSize(name=f"{self.name}-L", width=self.height, height=self.width, unit=self.unit)


# ANSI sizes (inches, landscape default for plats)
ANSI_A = PageSize("ANSI A", 11.0, 8.5, PageUnit.INCH)
ANSI_B = PageSize("ANSI B", 17.0, 11.0, PageUnit.INCH)
ANSI_C = PageSize("ANSI C", 22.0, 17.0, PageUnit.INCH)
ANSI_D = PageSize("ANSI D", 34.0, 22.0, PageUnit.INCH)
ANSI_E = PageSize("ANSI E", 44.0, 34.0, PageUnit.INCH)

# ARCH sizes (inches)
ARCH_A = PageSize("ARCH A", 12.0, 9.0, PageUnit.INCH)
ARCH_B = PageSize("ARCH B", 18.0, 12.0, PageUnit.INCH)
ARCH_C = PageSize("ARCH C", 24.0, 18.0, PageUnit.INCH)
ARCH_D = PageSize("ARCH D", 36.0, 24.0, PageUnit.INCH)
ARCH_E1 = PageSize("ARCH E1", 42.0, 30.0, PageUnit.INCH)

# ISO sizes (millimeters)
ISO_A4 = PageSize("ISO A4", 297.0, 210.0, PageUnit.MILLIMETER)
ISO_A3 = PageSize("ISO A3", 420.0, 297.0, PageUnit.MILLIMETER)
ISO_A2 = PageSize("ISO A2", 594.0, 420.0, PageUnit.MILLIMETER)
ISO_A1 = PageSize("ISO A1", 841.0, 594.0, PageUnit.MILLIMETER)
ISO_A0 = PageSize("ISO A0", 1189.0, 841.0, PageUnit.MILLIMETER)


PAGE_SIZES: dict[str, PageSize] = {
    p.name: p
    for p in (
        ANSI_A, ANSI_B, ANSI_C, ANSI_D, ANSI_E,
        ARCH_A, ARCH_B, ARCH_C, ARCH_D, ARCH_E1,
        ISO_A4, ISO_A3, ISO_A2, ISO_A1, ISO_A0,
    )
}


@dataclass(frozen=True, slots=True)
class TitleBlockInfo:
    """Title-block content. All fields optional; missing rows are skipped."""

    project_name: str
    sheet_title: str = "Boundary Survey"
    drawn_by: str | None = None
    checked_by: str | None = None
    surveyor_of_record: str | None = None
    license_state: str | None = None
    license_number: str | None = None
    job_number: str | None = None
    sheet_number: str = "1 of 1"
    revision: str | None = None
    date: str | None = None
    client: str | None = None
    address: str | None = None
    notes: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SheetLayoutSpec:
    """Inputs to :func:`build_sheet`."""

    page: PageSize
    title_block: TitleBlockInfo
    scale: float                # plan units per page unit (e.g. 50 ft/in)
    margin_in: float = 0.5
    plan_view_anchor: tuple[float, float] | None = None  # paperspace (x, y) of the plan-view center
    show_north_arrow: bool = True
    show_scale_bar: bool = True
    show_legend: bool = True
    preset: LayerPreset = DEFAULT_PRESET


def build_sheet(spec: SheetLayoutSpec, parcels: list[Parcel], output_path) -> int:
    """Create a single-sheet DXF with parcels placed on the page.

    Returns bytes written.
    """
    try:
        import ezdxf
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("ezdxf required") from e

    page = spec.page
    margin = spec.margin_in if page.unit is PageUnit.INCH else spec.margin_in * 25.4

    doc = ezdxf.new("R2018", setup=True)
    _ensure_linetypes(doc, spec.preset)
    _ensure_layers(doc, spec.preset)
    msp = doc.modelspace()

    # Sheet border
    border = spec.preset.resolve(SemanticLayer.SHEET_BORDER)
    msp.add_lwpolyline(
        [(margin, margin), (page.width - margin, margin),
         (page.width - margin, page.height - margin), (margin, page.height - margin),
         (margin, margin)],
        dxfattribs={"layer": border.name, "closed": True},
    )

    # Title block (lower-right)
    tb_w = min(page.width * 0.30, 7.0 if page.unit is PageUnit.INCH else 180)
    tb_h = min(page.height * 0.30, 4.5 if page.unit is PageUnit.INCH else 110)
    tb_origin = (page.width - margin - tb_w, margin)
    _draw_title_block(msp, tb_origin, tb_w, tb_h, spec.title_block, spec.preset)

    # Plan view: parcels drawn at scale, centered in the available area.
    plan_area_w = (page.width - 2 * margin) - tb_w - margin
    plan_area_h = page.height - 2 * margin
    plan_anchor = spec.plan_view_anchor or (margin + plan_area_w / 2, margin + plan_area_h / 2 + tb_h / 2)
    _draw_parcels_at_scale(msp, parcels, plan_anchor, spec.scale, spec.preset)

    if spec.show_north_arrow:
        na_radius = 0.5 if page.unit is PageUnit.INCH else 12
        _draw_north_arrow(msp, (page.width - margin - tb_w - na_radius * 2.5,
                                 page.height - margin - na_radius * 2),
                          na_radius, spec.preset)

    if spec.show_scale_bar:
        sb_x = margin + 0.5 if page.unit is PageUnit.INCH else margin + 12
        sb_y = margin + 0.4 if page.unit is PageUnit.INCH else margin + 10
        _draw_scale_bar(msp, (sb_x, sb_y), spec.scale, page.unit, spec.preset)

    if spec.show_legend:
        leg_x = margin + 0.5 if page.unit is PageUnit.INCH else margin + 12
        leg_y = page.height - margin - 0.5 if page.unit is PageUnit.INCH else page.height - margin - 12
        _draw_legend(msp, (leg_x, leg_y), spec.preset)

    doc.saveas(str(output_path))
    return output_path.stat().st_size if hasattr(output_path, "stat") else 0


# ── Drawing helpers ─────────────────────────────────────────────────────────


def _ensure_linetypes(doc, preset: LayerPreset) -> None:
    for name, pattern in preset.linetypes.items():
        if name in doc.linetypes:
            continue
        doc.linetypes.add(name=name, pattern=pattern, description=name)


def _ensure_layers(doc, preset: LayerPreset) -> None:
    for style in preset.layers.values():
        if style.name in doc.layers:
            continue
        layer = doc.layers.add(style.name)
        layer.color = style.color
        if style.linetype in doc.linetypes:
            layer.dxf.linetype = style.linetype
        layer.dxf.lineweight = style.lineweight


def _draw_title_block(msp, origin, w, h, info, preset):
    tb = preset.resolve(SemanticLayer.TITLE_BLOCK)
    border = preset.resolve(SemanticLayer.SHEET_BORDER)
    x, y = origin
    msp.add_lwpolyline(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
        dxfattribs={"layer": border.name, "closed": True},
    )

    rows = [
        ("PROJECT", info.project_name),
        ("SHEET", info.sheet_title),
        ("CLIENT", info.client),
        ("ADDRESS", info.address),
        ("SURVEYOR", info.surveyor_of_record),
        ("STATE / LICENSE", _join((info.license_state, info.license_number))),
        ("JOB #", info.job_number),
        ("DATE", info.date),
        ("DRAWN", info.drawn_by),
        ("CHECKED", info.checked_by),
        ("REVISION", info.revision),
        ("SHEET", info.sheet_number),
    ]
    rows = [(k, v) for k, v in rows if v]

    n = len(rows)
    if n == 0:
        return
    row_h = h / max(n, 1)
    text_h = min(row_h * 0.45, 0.18)

    for i, (label, value) in enumerate(rows):
        ry = y + h - (i + 1) * row_h
        msp.add_line((x, ry), (x + w, ry), dxfattribs={"layer": border.name})
        msp.add_text(
            label,
            dxfattribs={"layer": tb.name, "height": text_h * 0.85, "style": "STANDARD"},
        ).set_placement((x + 0.05, ry + row_h * 0.55))
        msp.add_text(
            str(value),
            dxfattribs={"layer": tb.name, "height": text_h, "style": "STANDARD"},
        ).set_placement((x + w * 0.35, ry + row_h * 0.30))


def _draw_parcels_at_scale(msp, parcels, anchor, scale, preset):
    boundary = preset.resolve(SemanticLayer.BOUNDARY)
    monuments = preset.resolve(SemanticLayer.MONUMENTS)
    if not parcels:
        return
    # Compute the combined bbox of all parcels in plan units.
    xs: list[float] = []
    ys: list[float] = []
    for parcel in parcels:
        if parcel.boundary is None:
            continue
        for p in parcel.boundary.polygon.exterior:
            xs.append(p.x)
            ys.append(p.y)
    if not xs:
        return
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2

    def to_paper(x: float, y: float) -> tuple[float, float]:
        # Plan-units to page-units via 1/scale.
        return ((x - cx) / scale + anchor[0], (y - cy) / scale + anchor[1])

    for parcel in parcels:
        if parcel.boundary is None:
            continue
        coords = [to_paper(p.x, p.y) for p in parcel.boundary.polygon.exterior]
        msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": boundary.name})
        pob = parcel.boundary.point_of_beginning
        ppx, ppy = to_paper(pob.x, pob.y)
        msp.add_circle((ppx, ppy), radius=0.05, dxfattribs={"layer": monuments.name})


def _draw_north_arrow(msp, center, radius, preset):
    na = preset.resolve(SemanticLayer.NORTH_ARROW)
    cx, cy = center
    # Outer circle
    msp.add_circle((cx, cy), radius=radius, dxfattribs={"layer": na.name})
    # Filled triangle pointing up
    points = [
        (cx, cy + radius * 0.95),
        (cx - radius * 0.45, cy - radius * 0.55),
        (cx + radius * 0.45, cy - radius * 0.55),
        (cx, cy + radius * 0.95),
    ]
    msp.add_lwpolyline(points, close=True, dxfattribs={"layer": na.name})
    msp.add_text(
        "N",
        dxfattribs={"layer": na.name, "height": radius * 0.45, "style": "STANDARD"},
    ).set_placement((cx, cy + radius * 1.1))


def _draw_scale_bar(msp, origin, scale, unit, preset):
    sb = preset.resolve(SemanticLayer.SCALE_BAR)
    x, y = origin
    bar_h = 0.08 if unit is PageUnit.INCH else 2.0
    n_segments = 4
    seg_w_paper = (1.0 if unit is PageUnit.INCH else 25.0)  # 1 in / 25 mm per segment
    seg_w_plan = seg_w_paper * scale  # in plan units

    for i in range(n_segments):
        sx = x + i * seg_w_paper
        ex = sx + seg_w_paper
        # Alternate filled / open
        msp.add_lwpolyline(
            [(sx, y), (ex, y), (ex, y + bar_h), (sx, y + bar_h), (sx, y)],
            dxfattribs={"layer": sb.name, "closed": True},
        )
        # Tick label
        msp.add_text(
            f"{int(i * seg_w_plan)}",
            dxfattribs={"layer": sb.name, "height": bar_h * 0.9, "style": "STANDARD"},
        ).set_placement((sx, y - bar_h * 1.6))
    # End label
    msp.add_text(
        f"{int(n_segments * seg_w_plan)}",
        dxfattribs={"layer": sb.name, "height": bar_h * 0.9, "style": "STANDARD"},
    ).set_placement((x + n_segments * seg_w_paper, y - bar_h * 1.6))
    # Title
    unit_label = "ft" if unit is PageUnit.INCH else "m"
    msp.add_text(
        f"SCALE 1″ = {scale:g} {unit_label}",
        dxfattribs={"layer": sb.name, "height": bar_h * 1.1, "style": "STANDARD"},
    ).set_placement((x, y + bar_h * 2.2))


def _draw_legend(msp, origin, preset):
    items = [
        (SemanticLayer.BOUNDARY, "Property Line"),
        (SemanticLayer.EASEMENTS, "Easement"),
        (SemanticLayer.ROW, "Right-of-Way"),
        (SemanticLayer.MONUMENTS, "Monument"),
        (SemanticLayer.CONTOURS_INDEX, "Index Contour"),
        (SemanticLayer.CONTOURS, "Minor Contour"),
    ]
    x, y = origin
    swatch_w = 0.5
    text_h = 0.12
    spacing = 0.22
    for i, (semantic, label) in enumerate(items):
        style = preset.resolve(semantic)
        ry = y - i * spacing
        msp.add_lwpolyline(
            [(x, ry), (x + swatch_w, ry)],
            dxfattribs={"layer": style.name},
        )
        msp.add_text(
            label,
            dxfattribs={"layer": style.name, "height": text_h, "style": "STANDARD"},
        ).set_placement((x + swatch_w + 0.1, ry - text_h * 0.4))


def _join(parts) -> str:
    return " — ".join(str(p) for p in parts if p)
