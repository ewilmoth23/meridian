"""DXF layer / style presets.

Surveyors typically standardise on one of a few layer schemes:

* **Default** — Meridian's opinionated palette (used by
  :class:`~meridian.adapters.cad.dxf_writer.DXFExporter` if the caller
  doesn't pass a preset).
* **ALTA/NSPS** — the layer naming used by ALTA/NSPS Land Title Survey
  deliverables.
* **Civil 3D** — Autodesk's default Civil 3D survey layers (so a
  Meridian DXF round-trips into Civil 3D without manual layer remapping).
* **NCS** — National CAD Standard (NCS) v6.

Each preset is a :class:`LayerPreset` that maps Meridian's *semantic*
layer names (e.g. ``BOUNDARY``, ``MONUMENTS``, ``CONTOURS``) to the
preset's preferred name + AutoCAD color index + linetype + lineweight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SemanticLayer(str, Enum):
    """Semantic layer ids used inside Meridian.

    The DXF writer takes a :class:`LayerPreset` and looks up each
    semantic layer to find the actual layer name + style to write.
    """

    BOUNDARY = "BOUNDARY"
    BOUNDARY_INTERIOR = "BOUNDARY_INTERIOR"
    MONUMENTS = "MONUMENTS"
    LABELS_BEARING_DIST = "LABELS_BEARING_DIST"
    LABELS_PARCEL = "LABELS_PARCEL"
    CONTROL_POINTS = "CONTROL_POINTS"
    ERROR_ELLIPSES = "ERROR_ELLIPSES"
    CONTOURS = "CONTOURS"
    CONTOURS_INDEX = "CONTOURS_INDEX"
    TIN_EDGES = "TIN_EDGES"
    EASEMENTS = "EASEMENTS"
    ROW = "ROW"  # right-of-way
    BUILDING_FOOTPRINTS = "BUILDING_FOOTPRINTS"
    UTILITY_LINES = "UTILITY_LINES"
    SHEET_BORDER = "SHEET_BORDER"
    TITLE_BLOCK = "TITLE_BLOCK"
    NORTH_ARROW = "NORTH_ARROW"
    SCALE_BAR = "SCALE_BAR"


@dataclass(frozen=True, slots=True)
class LayerStyle:
    """A single layer's name + AutoCAD style."""

    name: str
    color: int = 7              # AutoCAD Color Index — 7 = white/black
    linetype: str = "CONTINUOUS"
    lineweight: int = 25        # 0.25 mm × 100
    description: str | None = None


@dataclass(frozen=True, slots=True)
class LayerPreset:
    """A complete preset: semantic-layer → :class:`LayerStyle` mapping."""

    short_id: str
    display_name: str
    layers: dict[SemanticLayer, LayerStyle]
    linetypes: dict[str, str] = field(default_factory=dict)
    """Pattern strings for non-CONTINUOUS linetypes used by this preset."""

    def resolve(self, semantic: SemanticLayer) -> LayerStyle:
        """Look up the style for a semantic layer; falls back to a generic style."""
        return self.layers.get(semantic, LayerStyle(name=semantic.value, color=7))

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.layers.values()]


# ── Default Meridian preset ──────────────────────────────────────────────────

DEFAULT_LINETYPES = {
    "DASHED": "A,1,-0.5",
    "DASHED2": "A,0.6,-0.3",
    "CENTER": "A,1.25,-0.25,0.25,-0.25",
    "PHANTOM": "A,1.5,-0.25,0.25,-0.25,0.25,-0.25",
    "HIDDEN": "A,0.25,-0.125",
    "DOT": "A,0,-0.25",
}


DEFAULT_PRESET = LayerPreset(
    short_id="default",
    display_name="Meridian Default",
    layers={
        SemanticLayer.BOUNDARY:           LayerStyle("BOUNDARY",            color=4,   linetype="CONTINUOUS", lineweight=50, description="Parcel exterior"),
        SemanticLayer.BOUNDARY_INTERIOR:  LayerStyle("BOUNDARY-INTERIOR",   color=4,   linetype="DASHED",     lineweight=35, description="Parcel holes"),
        SemanticLayer.MONUMENTS:          LayerStyle("MONUMENTS",           color=1,   linetype="CONTINUOUS", lineweight=25),
        SemanticLayer.LABELS_BEARING_DIST: LayerStyle("LABELS-BEARING-DIST", color=7,  linetype="CONTINUOUS", lineweight=18),
        SemanticLayer.LABELS_PARCEL:      LayerStyle("LABELS-PARCEL",       color=7,   linetype="CONTINUOUS", lineweight=18),
        SemanticLayer.CONTROL_POINTS:     LayerStyle("CONTROL-POINTS",      color=2,   linetype="CONTINUOUS", lineweight=25),
        SemanticLayer.ERROR_ELLIPSES:     LayerStyle("ERROR-ELLIPSES",      color=6,   linetype="DASHED",     lineweight=18),
        SemanticLayer.CONTOURS:           LayerStyle("CONTOURS",            color=8,   linetype="CONTINUOUS", lineweight=18),
        SemanticLayer.CONTOURS_INDEX:     LayerStyle("CONTOURS-INDEX",      color=3,   linetype="CONTINUOUS", lineweight=35),
        SemanticLayer.TIN_EDGES:          LayerStyle("TIN-EDGES",           color=250, linetype="CONTINUOUS", lineweight=13),
        SemanticLayer.EASEMENTS:          LayerStyle("EASEMENTS",           color=6,   linetype="DASHED",     lineweight=25),
        SemanticLayer.ROW:                LayerStyle("ROW",                 color=5,   linetype="DASHED",     lineweight=35),
        SemanticLayer.BUILDING_FOOTPRINTS: LayerStyle("BUILDINGS",          color=6,   linetype="CONTINUOUS", lineweight=25),
        SemanticLayer.UTILITY_LINES:      LayerStyle("UTILITIES",           color=3,   linetype="DASHED2",    lineweight=18),
        SemanticLayer.SHEET_BORDER:       LayerStyle("SHEET-BORDER",        color=7,   linetype="CONTINUOUS", lineweight=50),
        SemanticLayer.TITLE_BLOCK:        LayerStyle("TITLE-BLOCK",         color=7,   linetype="CONTINUOUS", lineweight=18),
        SemanticLayer.NORTH_ARROW:        LayerStyle("NORTH-ARROW",         color=7,   linetype="CONTINUOUS", lineweight=25),
        SemanticLayer.SCALE_BAR:          LayerStyle("SCALE-BAR",           color=7,   linetype="CONTINUOUS", lineweight=25),
    },
    linetypes=DEFAULT_LINETYPES,
)


# ── ALTA/NSPS Land Title Survey preset ───────────────────────────────────────


ALTA_NSPS_PRESET = LayerPreset(
    short_id="alta_nsps",
    display_name="ALTA/NSPS Land Title Survey",
    layers={
        SemanticLayer.BOUNDARY:           LayerStyle("V-PROP-LINE",         color=2,  lineweight=50,  description="Subject property"),
        SemanticLayer.BOUNDARY_INTERIOR:  LayerStyle("V-PROP-EXCP",         color=2,  linetype="DASHED",  lineweight=35),
        SemanticLayer.MONUMENTS:          LayerStyle("V-PROP-MON",          color=1,  lineweight=25),
        SemanticLayer.LABELS_BEARING_DIST: LayerStyle("V-PROP-DIM",         color=7,  lineweight=18),
        SemanticLayer.LABELS_PARCEL:      LayerStyle("V-PROP-TEXT",         color=7,  lineweight=18),
        SemanticLayer.CONTROL_POINTS:     LayerStyle("V-CTRL-POINT",        color=4,  lineweight=25),
        SemanticLayer.ERROR_ELLIPSES:     LayerStyle("V-CTRL-ELL",          color=6,  linetype="DASHED",  lineweight=18),
        SemanticLayer.CONTOURS:           LayerStyle("V-CONT-MNR",          color=8,  lineweight=18),
        SemanticLayer.CONTOURS_INDEX:     LayerStyle("V-CONT-MAJR",         color=3,  lineweight=35),
        SemanticLayer.TIN_EDGES:          LayerStyle("V-TIN-EDGE",          color=250, lineweight=13),
        SemanticLayer.EASEMENTS:          LayerStyle("V-PROP-ESMT",         color=6,  linetype="DASHED",  lineweight=25),
        SemanticLayer.ROW:                LayerStyle("V-ROAD-RW",           color=5,  linetype="DASHED",  lineweight=35),
        SemanticLayer.BUILDING_FOOTPRINTS: LayerStyle("V-BLDG",              color=6,  lineweight=25),
        SemanticLayer.UTILITY_LINES:      LayerStyle("V-UTIL",              color=3,  linetype="DASHED2", lineweight=18),
        SemanticLayer.SHEET_BORDER:       LayerStyle("G-ANNO-TTLB-FRAM",    color=7,  lineweight=50),
        SemanticLayer.TITLE_BLOCK:        LayerStyle("G-ANNO-TTLB-TEXT",    color=7,  lineweight=18),
        SemanticLayer.NORTH_ARROW:        LayerStyle("G-ANNO-NORT",         color=7,  lineweight=25),
        SemanticLayer.SCALE_BAR:          LayerStyle("G-ANNO-SCAL",         color=7,  lineweight=25),
    },
    linetypes=DEFAULT_LINETYPES,
)


# ── Autodesk Civil 3D preset ─────────────────────────────────────────────────


CIVIL3D_PRESET = LayerPreset(
    short_id="civil3d",
    display_name="Autodesk Civil 3D Survey",
    layers={
        SemanticLayer.BOUNDARY:           LayerStyle("C-PROP-LINE",         color=4,  lineweight=50),
        SemanticLayer.BOUNDARY_INTERIOR:  LayerStyle("C-PROP-LINE-INNR",    color=4,  linetype="DASHED", lineweight=35),
        SemanticLayer.MONUMENTS:          LayerStyle("V-NODE-MMRK",         color=1,  lineweight=25),
        SemanticLayer.LABELS_BEARING_DIST: LayerStyle("C-PROP-LINE-TEXT",   color=7,  lineweight=18),
        SemanticLayer.LABELS_PARCEL:      LayerStyle("C-PROP-TEXT",         color=7,  lineweight=18),
        SemanticLayer.CONTROL_POINTS:     LayerStyle("V-NODE-CTRL",         color=2,  lineweight=25),
        SemanticLayer.ERROR_ELLIPSES:     LayerStyle("V-NODE-CTRL-ELLP",    color=6,  linetype="DASHED", lineweight=18),
        SemanticLayer.CONTOURS:           LayerStyle("C-TOPO-MINR",         color=8,  lineweight=18),
        SemanticLayer.CONTOURS_INDEX:     LayerStyle("C-TOPO-MAJR",         color=3,  lineweight=35),
        SemanticLayer.TIN_EDGES:          LayerStyle("C-TOPO-TIN",          color=250, lineweight=13),
        SemanticLayer.EASEMENTS:          LayerStyle("C-PROP-ESMT",         color=6,  linetype="DASHED", lineweight=25),
        SemanticLayer.ROW:                LayerStyle("C-ROAD-RW",           color=5,  linetype="DASHED", lineweight=35),
        SemanticLayer.BUILDING_FOOTPRINTS: LayerStyle("A-BLDG",              color=6,  lineweight=25),
        SemanticLayer.UTILITY_LINES:      LayerStyle("U-PROP",              color=3,  linetype="DASHED2", lineweight=18),
        SemanticLayer.SHEET_BORDER:       LayerStyle("G-ANNO-TTLB",         color=7,  lineweight=50),
        SemanticLayer.TITLE_BLOCK:        LayerStyle("G-ANNO-TTLB-TEXT",    color=7,  lineweight=18),
        SemanticLayer.NORTH_ARROW:        LayerStyle("G-ANNO-SYMB-NORT",    color=7,  lineweight=25),
        SemanticLayer.SCALE_BAR:          LayerStyle("G-ANNO-SYMB-SCAL",    color=7,  lineweight=25),
    },
    linetypes=DEFAULT_LINETYPES,
)


# ── National CAD Standard (NCS) v6 preset ────────────────────────────────────


NCS_PRESET = LayerPreset(
    short_id="ncs",
    display_name="National CAD Standard v6 (Survey)",
    layers={
        SemanticLayer.BOUNDARY:           LayerStyle("V-PROP-PLAT",         color=2,  lineweight=50),
        SemanticLayer.BOUNDARY_INTERIOR:  LayerStyle("V-PROP-PLAT-EXCP",    color=2,  linetype="DASHED", lineweight=35),
        SemanticLayer.MONUMENTS:          LayerStyle("V-PROP-MON",          color=1,  lineweight=25),
        SemanticLayer.LABELS_BEARING_DIST: LayerStyle("V-PROP-PLAT-DIM",    color=7,  lineweight=18),
        SemanticLayer.LABELS_PARCEL:      LayerStyle("V-PROP-PLAT-TEXT",    color=7,  lineweight=18),
        SemanticLayer.CONTROL_POINTS:     LayerStyle("V-NODE-CTRL",         color=4,  lineweight=25),
        SemanticLayer.ERROR_ELLIPSES:     LayerStyle("V-NODE-CTRL-ELL",     color=6,  linetype="DASHED", lineweight=18),
        SemanticLayer.CONTOURS:           LayerStyle("C-TOPO-MINR",         color=8,  lineweight=18),
        SemanticLayer.CONTOURS_INDEX:     LayerStyle("C-TOPO-MAJR",         color=3,  lineweight=35),
        SemanticLayer.TIN_EDGES:          LayerStyle("C-TOPO-TIN",          color=250, lineweight=13),
        SemanticLayer.EASEMENTS:          LayerStyle("V-PROP-ESMT",         color=6,  linetype="DASHED", lineweight=25),
        SemanticLayer.ROW:                LayerStyle("V-ROAD-RW",           color=5,  linetype="DASHED", lineweight=35),
        SemanticLayer.BUILDING_FOOTPRINTS: LayerStyle("A-BLDG-OTLN",         color=6,  lineweight=25),
        SemanticLayer.UTILITY_LINES:      LayerStyle("V-UTIL",              color=3,  linetype="DASHED2", lineweight=18),
        SemanticLayer.SHEET_BORDER:       LayerStyle("G-ANNO-TTLB-FRAM",    color=7,  lineweight=50),
        SemanticLayer.TITLE_BLOCK:        LayerStyle("G-ANNO-TTLB-TEXT",    color=7,  lineweight=18),
        SemanticLayer.NORTH_ARROW:        LayerStyle("G-ANNO-NORT",         color=7,  lineweight=25),
        SemanticLayer.SCALE_BAR:          LayerStyle("G-ANNO-SCAL",         color=7,  lineweight=25),
    },
    linetypes=DEFAULT_LINETYPES,
)


# ── Minimal preset (debugging / quick exports) ───────────────────────────────


MINIMAL_PRESET = LayerPreset(
    short_id="minimal",
    display_name="Minimal",
    layers={
        SemanticLayer.BOUNDARY:           LayerStyle("BOUNDARY",            color=7),
        SemanticLayer.BOUNDARY_INTERIOR:  LayerStyle("BOUNDARY",            color=7),
        SemanticLayer.MONUMENTS:          LayerStyle("MONUMENTS",           color=7),
        SemanticLayer.LABELS_BEARING_DIST: LayerStyle("LABELS",             color=7),
        SemanticLayer.LABELS_PARCEL:      LayerStyle("LABELS",              color=7),
        SemanticLayer.CONTROL_POINTS:     LayerStyle("CONTROL",             color=7),
        SemanticLayer.ERROR_ELLIPSES:     LayerStyle("CONTROL",             color=7),
        SemanticLayer.CONTOURS:           LayerStyle("CONTOURS",            color=7),
        SemanticLayer.CONTOURS_INDEX:     LayerStyle("CONTOURS",            color=7),
        SemanticLayer.TIN_EDGES:          LayerStyle("TIN",                 color=7),
        SemanticLayer.EASEMENTS:          LayerStyle("EASEMENTS",           color=7),
        SemanticLayer.ROW:                LayerStyle("ROW",                 color=7),
        SemanticLayer.BUILDING_FOOTPRINTS: LayerStyle("BLDG",               color=7),
        SemanticLayer.UTILITY_LINES:      LayerStyle("UTILITIES",           color=7),
        SemanticLayer.SHEET_BORDER:       LayerStyle("SHEET",               color=7),
        SemanticLayer.TITLE_BLOCK:        LayerStyle("TITLE",               color=7),
        SemanticLayer.NORTH_ARROW:        LayerStyle("NORTH",               color=7),
        SemanticLayer.SCALE_BAR:          LayerStyle("SCALE",               color=7),
    },
)


PRESETS: dict[str, LayerPreset] = {
    DEFAULT_PRESET.short_id: DEFAULT_PRESET,
    ALTA_NSPS_PRESET.short_id: ALTA_NSPS_PRESET,
    CIVIL3D_PRESET.short_id: CIVIL3D_PRESET,
    NCS_PRESET.short_id: NCS_PRESET,
    MINIMAL_PRESET.short_id: MINIMAL_PRESET,
}


def get_preset(name: str) -> LayerPreset:
    """Lookup by short_id; falls back to default with a clear error."""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown layer preset: {name!r}. Choose from: {sorted(PRESETS)}"
        )
    return PRESETS[name]
