"""Field-codes → CAD-feature pipeline.

When a survey crew records points in the field, every point carries a *code*
that tells the office what to do with it: ``EOP`` is edge-of-pavement,
``FH`` is a fire hydrant, ``BC``/``EC`` is the start/end of a curve, and so
on. Codes are concatenated when one point participates in multiple features
(``EOP BOC`` = both edge-of-pavement and back-of-curb at the same shot),
and decorated to mark feature boundaries (``+EOP1`` opens edge-of-pavement
feature 1, ``-EOP1`` closes it).

This module turns a flat list of :class:`FieldPoint` records into structured
:class:`FieldFeature` records ready to be drawn — each feature carries its
points, a target CAD layer, and a kind (``LINE``, ``SYMBOL``, ``BREAKLINE``,
``ARC``) so a downstream DXF / DWG / SVG writer knows how to emit it.

Code conventions supported in v0:

* **Multi-code points**: codes separated by spaces or commas (``"EOP BOC"``).
* **Feature numbering**: numeric suffix scopes the feature (``"EOP1"`` vs
  ``"EOP2"`` open two parallel pavement edges).
* **Feature delimiters**: a leading ``+`` or word ``BEG`` opens a new
  feature; ``-`` or ``END`` closes it. Without delimiters, consecutive
  points carrying the same (code, feature_number) belong to the same
  feature.
* **Curve markers**: ``BC`` (begin curve), ``EC`` (end curve), and ``CC``
  (curve point / centerpoint) attached to the same feature switch the
  segment between them to ``ARC``.
* **Comment codes**: a ``//`` introduces free-text description that is not
  part of any code.
* **Standard surveyor codebook**: a built-in dictionary of the ~50 most
  common codes (NCS-aligned + common Carlson/TDS conventions) — see
  :data:`STANDARD_CODEBOOK`.

What this module is *not*: it does not draw. It produces structured features
that the CAD adapters consume. The CAD writer is responsible for layer
creation, block insertion, line styling.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from meridian.domain.geometry import Point2D, Point3D

# ── Records ─────────────────────────────────────────────────────────────────


class CodeKind(str, Enum):
    """How a code's points should be drawn."""

    LINE = "line"           # connect-the-dots polyline
    ARC = "arc"             # 3-point arc (BC..points..EC)
    SYMBOL = "symbol"       # drop a CAD block at each point
    BREAKLINE = "breakline" # for surface modelling (TIN constraints)
    POINT = "point"         # plain point marker, no connection
    IGNORE = "ignore"       # used to mark codes consumed only as modifiers


@dataclass(frozen=True, slots=True)
class CodeDefinition:
    """Routing rule for a single field code."""

    code: str                          # canonical code, uppercased, no decorators
    kind: CodeKind
    layer: str
    description: str
    color: int = 7                     # AutoCAD Color Index hint
    linetype: str = "CONTINUOUS"
    block_name: str | None = None      # required for SYMBOL kind


@dataclass(frozen=True, slots=True)
class FieldPoint:
    """A single observed point with one or more codes."""

    point_number: int
    point: Point2D | Point3D
    raw_code: str
    description: str | None = None

    @property
    def coords(self) -> tuple[float, float, float | None]:
        if isinstance(self.point, Point3D):
            return (self.point.x, self.point.y, self.point.z)
        return (self.point.x, self.point.y, None)


@dataclass(frozen=True, slots=True)
class ParsedCode:
    """One token after parsing a raw code string.

    A single ``raw_code`` like ``"+EOP1 BOC"`` parses into two ``ParsedCode``s:

    * ``ParsedCode(code="EOP", feature_number=1, opens=True, ...)``
    * ``ParsedCode(code="BOC", feature_number=None, opens=False, ...)``
    """

    code: str
    feature_number: int | None = None
    opens: bool = False
    closes: bool = False
    is_curve_begin: bool = False
    is_curve_end: bool = False


@dataclass(frozen=True, slots=True)
class FieldFeature:
    """A CAD-ready feature derived from one or more :class:`FieldPoint`."""

    code: str
    feature_number: int | None
    kind: CodeKind
    layer: str
    points: tuple[Point2D | Point3D, ...]
    description: str
    block_name: str | None = None
    color: int = 7
    linetype: str = "CONTINUOUS"
    point_numbers: tuple[int, ...] = ()

    @property
    def is_3d(self) -> bool:
        return all(isinstance(p, Point3D) for p in self.points)


# ── Code book ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CodeBook:
    """A collection of code definitions."""

    definitions: dict[str, CodeDefinition] = field(default_factory=dict)
    """Map from canonical code (uppercased) to its definition."""

    fallback_layer: str = "FIELD-UNKNOWN"
    fallback_kind: CodeKind = CodeKind.POINT

    def lookup(self, code: str) -> CodeDefinition:
        code = code.upper()
        if code in self.definitions:
            return self.definitions[code]
        return CodeDefinition(
            code=code,
            kind=self.fallback_kind,
            layer=self.fallback_layer,
            description=f"Unknown code {code!r}",
        )

    def with_definition(self, defn: CodeDefinition) -> CodeBook:
        new = dict(self.definitions)
        new[defn.code.upper()] = defn
        return CodeBook(definitions=new, fallback_layer=self.fallback_layer, fallback_kind=self.fallback_kind)


def _line(code: str, layer: str, desc: str, *, color: int = 7, linetype: str = "CONTINUOUS") -> CodeDefinition:
    return CodeDefinition(code=code, kind=CodeKind.LINE, layer=layer, description=desc, color=color, linetype=linetype)


def _sym(code: str, layer: str, desc: str, *, block: str, color: int = 7) -> CodeDefinition:
    return CodeDefinition(code=code, kind=CodeKind.SYMBOL, layer=layer, description=desc, block_name=block, color=color)


def _bl(code: str, layer: str, desc: str) -> CodeDefinition:
    return CodeDefinition(code=code, kind=CodeKind.BREAKLINE, layer=layer, description=desc)


# Standard codebook — a starter set covering the most common land-survey
# codes used by Carlson, TDS, Trimble, and Leica data collectors. Surveyors
# routinely override this with a project-specific book; that's why we expose
# ``CodeBook.with_definition``.
STANDARD_CODEBOOK = CodeBook(
    definitions={
        # Pavement / road
        "EOP":  _line("EOP",  "ROAD-EOP",       "Edge of pavement",       color=3),
        "EP":   _line("EP",   "ROAD-EOP",       "Edge of pavement",       color=3),
        "BOC":  _line("BOC",  "ROAD-BOC",       "Back of curb",           color=4),
        "TOC":  _line("TOC",  "ROAD-TOC",       "Top of curb",            color=4),
        "FOC":  _line("FOC",  "ROAD-FOC",       "Face of curb",           color=4),
        "CL":   _line("CL",   "ROAD-CL",        "Centerline",             color=2, linetype="CENTER"),
        "GUTTER": _line("GUTTER", "ROAD-GUTTER", "Gutter line",           color=4),
        "SW":   _line("SW",   "ROAD-SIDEWALK",  "Sidewalk",               color=8),
        "DW":   _line("DW",   "ROAD-DRIVEWAY",  "Driveway",               color=8),
        # Curves
        "BC":   CodeDefinition(code="BC", kind=CodeKind.IGNORE, layer="", description="Begin-curve marker"),
        "EC":   CodeDefinition(code="EC", kind=CodeKind.IGNORE, layer="", description="End-curve marker"),
        "PC":   CodeDefinition(code="PC", kind=CodeKind.IGNORE, layer="", description="Point of curvature"),
        "PT":   CodeDefinition(code="PT", kind=CodeKind.IGNORE, layer="", description="Point of tangency"),
        # Boundary / property
        "PL":   _line("PL",   "BOUNDARY-PL",    "Property line",          color=1),
        "RW":   _line("RW",   "BOUNDARY-RW",    "Right-of-way line",      color=1, linetype="DASHED"),
        "FENCE": _line("FENCE", "FENCE",        "Fence",                  color=8, linetype="DASHED2"),
        "WALL": _line("WALL", "WALL",           "Retaining/garden wall",  color=8),
        # Buildings
        "BLDG": _line("BLDG", "BUILDING",       "Building outline",       color=5),
        "CONC": _line("CONC", "CONCRETE",       "Concrete pad",           color=8),
        # Utilities — symbols
        "FH":   _sym("FH",   "UTIL-WATER",      "Fire hydrant",           block="FH_BLOCK", color=1),
        "WV":   _sym("WV",   "UTIL-WATER",      "Water valve",            block="WV_BLOCK", color=4),
        "WM":   _sym("WM",   "UTIL-WATER",      "Water meter",            block="WM_BLOCK", color=4),
        "MH":   _sym("MH",   "UTIL-SANITARY",   "Sanitary manhole",       block="MH_BLOCK", color=2),
        "SDMH": _sym("SDMH", "UTIL-STORM",      "Storm drain manhole",    block="MH_BLOCK", color=5),
        "CO":   _sym("CO",   "UTIL-SANITARY",   "Cleanout",               block="CO_BLOCK", color=2),
        "CB":   _sym("CB",   "UTIL-STORM",      "Catch basin",            block="CB_BLOCK", color=5),
        "GAS":  _sym("GAS",  "UTIL-GAS",        "Gas valve / marker",     block="GAS_BLOCK", color=2),
        "PP":   _sym("PP",   "UTIL-ELECTRIC",   "Power pole",             block="PP_BLOCK", color=6),
        "GW":   _sym("GW",   "UTIL-ELECTRIC",   "Guy wire anchor",        block="GW_BLOCK", color=6),
        "TP":   _sym("TP",   "UTIL-COMM",       "Telephone pedestal",     block="TP_BLOCK", color=2),
        "EM":   _sym("EM",   "UTIL-ELECTRIC",   "Electric meter",         block="EM_BLOCK", color=6),
        "SIGN": _sym("SIGN", "SIGN",            "Sign",                   block="SIGN_BLOCK", color=7),
        # Trees / vegetation
        "TR":   _sym("TR",   "VEG-TREE",        "Tree",                   block="TREE_BLOCK", color=3),
        "BUSH": _sym("BUSH", "VEG-BUSH",        "Bush / shrub",           block="BUSH_BLOCK", color=3),
        # Topography (breaklines for TIN)
        "TOE":  _bl("TOE",   "TOPO-TOE",        "Toe of slope"),
        "TOP":  _bl("TOP",   "TOPO-TOP",        "Top of slope"),
        "DITCH": _bl("DITCH", "TOPO-DITCH",     "Ditch / swale"),
        "RIDGE": _bl("RIDGE", "TOPO-RIDGE",     "Ridge"),
        "BERM": _bl("BERM",  "TOPO-BERM",       "Berm"),
        # Spot shots — point only
        "GS":   CodeDefinition(code="GS", kind=CodeKind.POINT, layer="TOPO-GS", description="Ground spot"),
        "TBM":  CodeDefinition(code="TBM", kind=CodeKind.POINT, layer="CONTROL-TBM", description="Temporary benchmark", color=2),
        "CP":   CodeDefinition(code="CP", kind=CodeKind.POINT, layer="CONTROL-CP", description="Control point", color=2),
        "MON":  CodeDefinition(code="MON", kind=CodeKind.POINT, layer="MONUMENTS", description="Monument", color=1),
        "IPF":  CodeDefinition(code="IPF", kind=CodeKind.POINT, layer="MONUMENTS", description="Iron pin found", color=1),
        "IPS":  CodeDefinition(code="IPS", kind=CodeKind.POINT, layer="MONUMENTS", description="Iron pin set", color=1),
    },
)


# ── Code parser ─────────────────────────────────────────────────────────────


_CODE_TOKEN = re.compile(
    r"""
    ^
    (?P<delim>[+\-]|BEG|END)?      # optional open/close marker
    (?P<base>[A-Za-z]+)            # alpha base code
    (?P<num>\d+)?                  # optional numeric feature id
    $
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_raw_code(raw: str) -> tuple[ParsedCode, ...]:
    """Tokenise a raw code string into ``ParsedCode`` records.

    Splitting rules: tokens are separated by spaces or commas. Anything after
    a ``//`` is treated as comment and discarded. Tokens that don't match the
    pattern are silently dropped (data-collector noise).
    """
    if not raw:
        return ()
    raw = raw.split("//", 1)[0]
    parts = re.split(r"[\s,]+", raw.strip())
    out: list[ParsedCode] = []
    for token in parts:
        if not token:
            continue
        m = _CODE_TOKEN.match(token)
        if not m:
            continue
        delim = (m.group("delim") or "").upper()
        base = m.group("base").upper()
        num = m.group("num")
        opens = delim in ("+", "BEG")
        closes = delim in ("-", "END")
        out.append(
            ParsedCode(
                code=base,
                feature_number=int(num) if num else None,
                opens=opens,
                closes=closes,
                is_curve_begin=base == "BC",
                is_curve_end=base in ("EC", "PT"),
            )
        )
    return tuple(out)


# ── Feature builder ─────────────────────────────────────────────────────────


def build_features(
    points: Iterable[FieldPoint],
    codebook: CodeBook = STANDARD_CODEBOOK,
) -> tuple[FieldFeature, ...]:
    """Walk an ordered list of ``FieldPoint`` and emit ``FieldFeature``.

    Algorithm:
    1. For each point, parse its raw code into ``ParsedCode`` tokens.
    2. For each non-IGNORE token, append the point to the open feature
       identified by ``(code, feature_number)``. If no open feature exists
       (or the token starts with ``+``), open a new one.
    3. A trailing ``-`` / ``END`` closes the matching feature.
    4. After all points are consumed, emit any still-open features in input
       order, then collapse trailing curve markers (``BC``/``EC``) onto the
       parent feature so it renders as an ``ARC`` segment.
    """
    pts = list(points)
    open_features: dict[tuple[str, int | None], _OpenFeature] = {}
    closed: list[FieldFeature] = []
    order: list[tuple[str, int | None]] = []

    for fp in pts:
        tokens = parse_raw_code(fp.raw_code)
        # Track which features this point already joined to allow closing them.
        joined: list[tuple[str, int | None]] = []
        # Curve flags raise on the parent feature when BC/EC accompany a real code.
        curve_open_for: list[tuple[str, int | None]] = []
        curve_close_for: list[tuple[str, int | None]] = []

        for tok in tokens:
            defn = codebook.lookup(tok.code)
            if defn.kind is CodeKind.IGNORE:
                # BC/EC carry no feature themselves; they decorate the *other*
                # codes on this point. We mark them to apply after the loop.
                if tok.is_curve_begin:
                    curve_open_for.extend(joined)  # apply to features already joined this shot
                if tok.is_curve_end:
                    curve_close_for.extend(joined)
                continue

            key = (defn.code, tok.feature_number)
            joined.append(key)

            # Open or continue.
            if key not in open_features or tok.opens:
                if key in open_features:
                    # Close previous instance first (the new + restarts it).
                    closed.append(open_features[key].finalize(defn))
                    order.remove(key)
                open_features[key] = _OpenFeature(definition=defn, feature_number=tok.feature_number)
                order.append(key)

            of = open_features[key]
            of.add_point(fp)

            if tok.is_curve_begin or (tok.opens and tok.code == "BC"):
                of.curve_open = True
            if tok.is_curve_end:
                of.curve_close = True

            if tok.closes:
                closed.append(of.finalize(defn))
                del open_features[key]
                order.remove(key)

        # BC tokens on this point apply to every feature this point just joined.
        for k in curve_open_for:
            if k in open_features:
                open_features[k].curve_open_at = len(open_features[k].points) - 1
        for k in curve_close_for:
            if k in open_features:
                open_features[k].curve_close_at = len(open_features[k].points) - 1

    # Emit anything still open, in original opening order.
    for key in order:
        of = open_features[key]
        closed.append(of.finalize(of.definition))

    # Symbols and bare points don't connect — split multi-point features of
    # those kinds into one feature per point so a downstream renderer can
    # insert one block per shot.
    expanded: list[FieldFeature] = []
    for f in closed:
        if f.kind in (CodeKind.SYMBOL, CodeKind.POINT) and len(f.points) > 1:
            for p, pn in zip(f.points, f.point_numbers, strict=True):
                expanded.append(
                    FieldFeature(
                        code=f.code,
                        feature_number=f.feature_number,
                        kind=f.kind,
                        layer=f.layer,
                        points=(p,),
                        description=f.description,
                        block_name=f.block_name,
                        color=f.color,
                        linetype=f.linetype,
                        point_numbers=(pn,),
                    )
                )
        else:
            expanded.append(f)

    # Sort by first point number for stable, predictable output.
    expanded.sort(key=lambda f: f.point_numbers[0] if f.point_numbers else 0)
    return tuple(expanded)


@dataclass
class _OpenFeature:
    definition: CodeDefinition
    feature_number: int | None
    points: list[FieldPoint] = field(default_factory=list)
    curve_open: bool = False
    curve_close: bool = False
    curve_open_at: int | None = None
    curve_close_at: int | None = None

    def add_point(self, fp: FieldPoint) -> None:
        self.points.append(fp)

    def finalize(self, defn: CodeDefinition) -> FieldFeature:
        kind = defn.kind
        if (self.curve_open or self.curve_open_at is not None) and (
            self.curve_close or self.curve_close_at is not None
        ):
            kind = CodeKind.ARC
        # Symbols and POINT kinds don't connect; emit one feature per point.
        return FieldFeature(
            code=defn.code,
            feature_number=self.feature_number,
            kind=kind,
            layer=defn.layer,
            points=tuple(fp.point for fp in self.points),
            description=defn.description,
            block_name=defn.block_name,
            color=defn.color,
            linetype=defn.linetype,
            point_numbers=tuple(fp.point_number for fp in self.points),
        )


# ── Convenience: batch parse from PNEZD-like rows ──────────────────────────


_PNEZD_LINE = re.compile(
    r"""
    ^\s*
    (?P<num>\d+)\s*[,\s]\s*
    (?P<n>-?\d+(?:\.\d+)?)\s*[,\s]\s*
    (?P<e>-?\d+(?:\.\d+)?)\s*[,\s]\s*
    (?P<z>-?\d+(?:\.\d+)?)
    (?:\s*[,\s]\s*(?P<code>.*))?
    \s*$
    """,
    re.VERBOSE,
)


def parse_pnezd(
    text: str, *, crs, two_d_only: bool = False
) -> tuple[FieldPoint, ...]:
    """Parse a PNEZD (Point#, Northing, Easting, Z, Description/Code) file.

    PNEZD is the lingua franca of survey data exchange — every data
    collector exports it. ``crs`` is the CRS of the coordinates. If
    ``two_d_only`` is ``True``, the Z column is read but discarded
    (returns Point2D instead of Point3D).

    Lines that don't parse are silently skipped (typical for headers and
    blank lines).
    """
    out: list[FieldPoint] = []
    for raw_line in text.splitlines():
        m = _PNEZD_LINE.match(raw_line)
        if not m:
            continue
        n = float(m.group("n"))
        e = float(m.group("e"))
        z = float(m.group("z"))
        code = (m.group("code") or "").strip()
        # PNEZD convention: northing first, but our Point2D is x=east, y=north.
        if two_d_only:
            pt: Point2D | Point3D = Point2D(x=e, y=n, crs=crs)
        else:
            pt = Point3D(x=e, y=n, z=z, crs=crs)
        out.append(
            FieldPoint(
                point_number=int(m.group("num")),
                point=pt,
                raw_code=code,
            )
        )
    return tuple(out)


__all__ = [
    "STANDARD_CODEBOOK",
    "CodeBook",
    "CodeDefinition",
    "CodeKind",
    "FieldFeature",
    "FieldPoint",
    "ParsedCode",
    "build_features",
    "parse_pnezd",
    "parse_raw_code",
]
