"""Public Land Survey System (PLSS) parser and boundary computer.

The PLSS divides 30 western US states into a grid of:

    Township (T)      — a 6 × 6 mile block, indexed N/S of a baseline
    Range    (R)      — 6 mile column,         indexed E/W of a meridian
    Section           — 1 mile × 1 mile (1/36 of a township), numbered 1..36
    Aliquot           — recursive 1/2 or 1/4 subdivisions: NW¼ of SE¼, etc.

Section numbering uses the *boustrophedon* / *serpentine* pattern: it
starts at the NE corner (Section 1) and snakes across each row.

This module:

* Recognises a PLSS-style legal description in free text.
* Parses Township / Range / Section / aliquot parts into structured records.
* Computes the section corners and aliquot polygons in *township-relative*
  meters (origin at the SW corner of the township).
* Provides a :func:`plss_polygon` convenience that produces a domain
  :class:`~meridian.domain.geometry.Polygon` ready to drop into a
  :class:`~meridian.domain.parcel.Parcel`.

We do not (yet) georeference to lat/lon; that requires a NADCON5 grid
shift from each principal meridian's local datum to NAD83(2011), which
lands in v0.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.crs import CRS


# ── Constants ──────────────────────────────────────────────────────────────

_FT_PER_MILE = 5280.0
_FT_PER_M = 1 / 0.3048
_MILE_M = _FT_PER_MILE / _FT_PER_M     # ≈ 1609.344
_TOWNSHIP_M = 6 * _MILE_M              # 6 mi
_SECTION_M = _MILE_M                   # 1 mi
_QUARTER_M = _MILE_M / 2
_QUARTER_QUARTER_M = _MILE_M / 4
_QUARTER_QUARTER_QUARTER_M = _MILE_M / 8


# Principal Meridians of the United States (37 of them).
PRINCIPAL_MERIDIANS = (
    "1st", "2nd", "3rd", "4th", "5th", "6th",
    "Black Hills", "Boise", "Chickasaw", "Choctaw", "Cimarron",
    "Copper River", "Fairbanks", "Gila and Salt River", "Humboldt",
    "Huntsville", "Indian", "Kateel River", "Louisiana", "Michigan",
    "Mount Diablo", "Navajo", "New Mexico", "Salt Lake", "San Bernardino",
    "Seward", "St. Helena", "St. Stephens", "Tallahassee",
    "Uintah Special", "Umiat", "Ute", "Washington", "Willamette",
    "Wind River", "Ohio River Survey", "Connecticut Western Reserve",
)


class Direction(str, Enum):
    NORTH = "N"
    SOUTH = "S"
    EAST = "E"
    WEST = "W"


@dataclass(frozen=True, slots=True)
class TownshipRange:
    """A T/R designator: e.g. ``T2N R3E``."""

    township: int
    township_dir: Direction       # N or S relative to baseline
    range: int
    range_dir: Direction          # E or W relative to meridian
    meridian: str | None = None

    def label(self) -> str:
        m = f", {self.meridian} P.M." if self.meridian else ""
        return f"T{self.township}{self.township_dir.value} R{self.range}{self.range_dir.value}{m}"


@dataclass(frozen=True, slots=True)
class AliquotPart:
    """An aliquot subdivision string like ``NW1/4 of SE1/4``.

    Stored as a sequence of cardinal-quarter steps from outer to inner:
    ``("NW", "SE")`` means "NW quarter of the SE quarter" — successively
    smaller boxes.
    """

    parts: tuple[str, ...]

    def label(self) -> str:
        if not self.parts:
            return "(whole)"
        return " of ".join(f"{p}¼" for p in self.parts)


@dataclass(frozen=True, slots=True)
class PLSSDescription:
    """Parsed PLSS legal description."""

    township_range: TownshipRange
    section: int
    aliquot: AliquotPart | None
    raw_text: str | None = None

    def label(self) -> str:
        bits = []
        if self.aliquot:
            bits.append(self.aliquot.label())
        bits.append(f"Sec {self.section}")
        bits.append(self.township_range.label())
        return ", ".join(bits)


# ── Parsing ─────────────────────────────────────────────────────────────────


_TR_RE = re.compile(
    r"""
    (?:Township|T)\.?\s*
    (?P<t>\d{1,3})\s*
    (?P<td>North|South|N|S)\.?
    [\s,]+
    (?:Range|R)\.?\s*
    (?P<r>\d{1,3})\s*
    (?P<rd>East|West|E|W)\.?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SECTION_RE = re.compile(
    r"""
    (?:Section|Sec\.?)\s*(?P<s>\d{1,2})
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ALIQUOT_RE = re.compile(
    r"""
    (?:
        (?:Northeast|Northwest|Southeast|Southwest|NE|NW|SE|SW)
        \s*(?:1/4|¼|quarter)
    )
    (?:\s+of\s+the?\s+
        (?:Northeast|Northwest|Southeast|Southwest|NE|NW|SE|SW)
        \s*(?:1/4|¼|quarter)
    )*
    """,
    re.IGNORECASE | re.VERBOSE,
)

_QUARTER_TOKEN_RE = re.compile(
    r"(Northeast|Northwest|Southeast|Southwest|NE|NW|SE|SW)\s*(?:1/4|¼|quarter)",
    re.IGNORECASE,
)


_MERIDIAN_RE = re.compile(
    r"\b("
    + "|".join(re.escape(m) for m in PRINCIPAL_MERIDIANS)
    + r")\s*(?:Principal\s+)?(?:Meridian|P\.?\s*M\.?)\b",
    re.IGNORECASE,
)


_QUARTER_LONG_TO_SHORT = {
    "northeast": "NE",
    "northwest": "NW",
    "southeast": "SE",
    "southwest": "SW",
    "ne": "NE",
    "nw": "NW",
    "se": "SE",
    "sw": "SW",
}


def _normalize_quarter(token: str) -> str:
    """Map ``Northwest`` / ``NW`` / ``northwest`` → canonical ``NW``."""
    return _QUARTER_LONG_TO_SHORT[token.lower()]


def is_plss_description(text: str) -> bool:
    """Quick sniff: does the text look like a PLSS legal description?"""
    return bool(_TR_RE.search(text) and _SECTION_RE.search(text))


def parse_plss(text: str) -> PLSSDescription:
    """Parse a PLSS-style legal description.

    Raises :class:`ValueError` when the text doesn't carry both a
    Township/Range and a Section reference.
    """
    tr_match = _TR_RE.search(text)
    sec_match = _SECTION_RE.search(text)
    if not tr_match or not sec_match:
        raise ValueError(
            f"Not a PLSS description (missing T/R or Section): {text[:120]!r}"
        )

    meridian = None
    m = _MERIDIAN_RE.search(text)
    if m:
        meridian = m.group(1)

    aliquot_match = _ALIQUOT_RE.search(text)
    aliquot = None
    if aliquot_match:
        toks = [_normalize_quarter(t.group(1)) for t in _QUARTER_TOKEN_RE.finditer(aliquot_match.group(0))]
        aliquot = AliquotPart(parts=tuple(toks))

    return PLSSDescription(
        township_range=TownshipRange(
            township=int(tr_match.group("t")),
            township_dir=Direction(tr_match.group("td").upper()[0]),
            range=int(tr_match.group("r")),
            range_dir=Direction(tr_match.group("rd").upper()[0]),
            meridian=meridian,
        ),
        section=int(sec_match.group("s")),
        aliquot=aliquot,
        raw_text=text.strip(),
    )


# ── Section-corner geometry (township-relative) ─────────────────────────────


def section_corners(section: int) -> tuple[float, float, float, float]:
    """SW corner (x, y) and (width, height) of a section in township-relative meters.

    Sections are numbered serpentine starting at the NE corner (Section 1)
    going west to Section 6 in the top row, then jumping to Section 7
    just below 6 going east, etc.
    """
    if not 1 <= section <= 36:
        raise ValueError(f"Section must be 1..36, got {section}")
    # Row 0 is the top row (north); section 1 is NE → row 0, col 5.
    idx = section - 1
    row = idx // 6                    # 0..5; 0 = top
    col_in_row = idx % 6
    # Even rows (top, then alternating) read right-to-left.
    if row % 2 == 0:
        col = 5 - col_in_row
    else:
        col = col_in_row
    # SW corner of the section in township-relative coords (origin at SW corner of T)
    x = col * _SECTION_M
    y = (5 - row) * _SECTION_M
    return x, y, _SECTION_M, _SECTION_M


def aliquot_box(section: int, aliquot: AliquotPart | None) -> tuple[float, float, float, float]:
    """Compute the SW corner + size of a section + aliquot subdivision.

    Returns ``(sw_x, sw_y, width, height)`` in township-relative meters.
    """
    sw_x, sw_y, w, h = section_corners(section)
    if aliquot is None or not aliquot.parts:
        return sw_x, sw_y, w, h
    # Successively narrow the box.
    for q in aliquot.parts:
        cx = sw_x + w / 2
        cy = sw_y + h / 2
        if q == "NE":
            sw_x, sw_y = cx, cy
        elif q == "NW":
            sw_x, sw_y = sw_x, cy
        elif q == "SE":
            sw_x, sw_y = cx, sw_y
        elif q == "SW":
            sw_x, sw_y = sw_x, sw_y
        else:  # pragma: no cover
            raise ValueError(f"Bad aliquot quarter: {q!r}")
        w /= 2
        h /= 2
    return sw_x, sw_y, w, h


def plss_polygon(
    description: PLSSDescription,
    crs: CRS,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
):
    """Produce a closed :class:`Polygon` in the given CRS for the description.

    The polygon's SW corner is placed at ``origin`` (default = origin of the
    target CRS). For real georeferenced output, callers should compute the
    correct origin from the principal-meridian baseline + the township
    offset and pass it in.
    """
    from meridian.domain.geometry import Point2D, Polygon

    sw_x, sw_y, w, h = aliquot_box(description.section, description.aliquot)
    ox = origin[0] + sw_x
    oy = origin[1] + sw_y
    pts = (
        Point2D(ox, oy, crs),
        Point2D(ox + w, oy, crs),
        Point2D(ox + w, oy + h, crs),
        Point2D(ox, oy + h, crs),
        Point2D(ox, oy, crs),
    )
    return Polygon(exterior=pts).oriented()


# ── Section/township area helpers ───────────────────────────────────────────


def section_area_acres(aliquot: AliquotPart | None) -> float:
    """Nominal area of a section + aliquot subdivision in acres."""
    base = 640.0
    if aliquot is None:
        return base
    return base / (4 ** len(aliquot.parts))
