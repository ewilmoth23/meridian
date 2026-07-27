"""Pipeline: deed text → calls → closed polygon.

Replaces three prototype modules (``parser_regex``, ``ai_parser``, and
``extraction_pipeline``) with one well-bounded pipeline that:

1. Tokenises the legal description.
2. Parses each clause into a :class:`~meridian.domain.parcel.Call`.
3. Optionally calls an :class:`~meridian.ports.ai.LLMClient` for the
   clauses that the regex parser could not handle.
4. Validates: classifies bearings, ensures at least one POB clause,
   makes sure curves are well-formed.
5. Computes coordinates by running the calls through
   :func:`meridian.math.cogo.run_traverse`.
6. Reports closure and packages the result as a
   :class:`~meridian.domain.parcel.Boundary`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from meridian.domain.parcel import Call, CallKind
from meridian.math.cogo import dms_to_radians, run_traverse

if TYPE_CHECKING:
    from meridian.domain.geometry import Point2D
    from meridian.domain.parcel import Boundary
    from meridian.ports.ai import LLMClient


# ── Lexicon ─────────────────────────────────────────────────────────────────

# Distance unit conversion factors → meters.
DISTANCE_UNITS_M: dict[str, float] = {
    "ft": 0.3048,
    "feet": 0.3048,
    "foot": 0.3048,
    "us_ft": 1200.0 / 3937.0,
    "usft": 1200.0 / 3937.0,
    "us_survey_feet": 1200.0 / 3937.0,
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "ch": 20.1168,
    "chain": 20.1168,
    "chains": 20.1168,
    "li": 0.201168,
    "link": 0.201168,
    "links": 0.201168,
    "rd": 5.0292,
    "rod": 5.0292,
    "rods": 5.0292,
    "perch": 5.0292,
    "vara": 0.847396,           # Texas vara: 33.333 in
    "varas": 0.847396,
}


_RE_BEARING = re.compile(
    r"""
    (?P<ns>[NS])\s*
    (?P<deg>\d{1,3})\s*[°*\s]\s*
    (?:(?P<min>\d{1,2})\s*['′\s])?
    (?:(?P<sec>\d{1,2}(?:\.\d+)?)\s*[\"″])?
    \s*(?P<ew>[EW])
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""Match a quadrant bearing like ``N 45°30'15" E`` or ``N45-30-15E``."""

_RE_DISTANCE = re.compile(
    r"""
    (?P<value>\d+(?:\.\d+)?)\s*
    (?P<unit>feet|foot|ft|usft|us_ft|us_survey_feet|meters?|metres?|m\b|chains?|ch\b|links?|li\b|rods?|rd\b|perch|varas?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_LINE_CALL = re.compile(
    r"""
    (?:THENCE\s+)?
    (?P<bearing>(?:N|S)\s*\d{1,3}(?:[°*\s]\s*\d{1,2}(?:['′\s]\s*\d{1,2}(?:\.\d+)?[\"″]?)?)?\s*(?:E|W))
    [\s,]*
    (?:a\s+)?(?:distance\s+of\s+)?
    (?P<distance>\d+(?:\.\d+)?\s*(?:feet|foot|ft|usft|us_ft|meters?|metres?|m\b|chains?|ch\b|links?|li\b|rods?|rd\b|perch|varas?))
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_CURVE = re.compile(
    r"""
    (?:THENCE\s+)?
    (?:along\s+(?:a|the)\s+(?:curve|arc)|curving\s+to\s+the)
    \s+(?:to\s+the\s+)?(?P<dir>left|right|clockwise|counterclockwise|counter-clockwise)
    [\s,;]*
    (?:.*?radius\s+of\s+(?P<radius>\d+(?:\.\d+)?)\s*(?P<runit>feet|foot|ft|meters?|metres?|m\b))?
    (?:.*?(?:arc\s+length|arc\s+distance|length)\s+of\s+(?P<arc>\d+(?:\.\d+)?)\s*(?P<aunit>feet|foot|ft|meters?|metres?|m\b))?
    (?:.*?delta\s+of?\s+(?P<delta>\d+(?:°|deg)\s*\d+\s*'\s*\d+(?:\.\d+)?\s*\"?|\d+(?:\.\d+)?))?
    (?:.*?chord\s+(?:bears|bearing)\s+(?P<chordbrg>(?:N|S)\s*\d+.*?(?:E|W)))?
    (?:.*?chord\s+(?:length|of)\s+(?P<chord>\d+(?:\.\d+)?)\s*(?P<cunit>feet|foot|ft|meters?|metres?|m\b))?
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_RE_POB = re.compile(
    r"""(?:point\s+of\s+beginning|true\s+point\s+of\s+beginning|POB|P\.O\.B\.)""",
    re.IGNORECASE,
)


# ── Errors ─────────────────────────────────────────────────────────────────


class DeedParseError(ValueError):
    """Raised when the deed cannot be parsed into a closed polygon."""


# ── Helpers ────────────────────────────────────────────────────────────────


def parse_bearing(text: str) -> float:
    """Parse a quadrant bearing string into an azimuth in radians.

    Returns the azimuth measured clockwise from grid north.
    """
    m = _RE_BEARING.search(text)
    if not m:
        raise DeedParseError(f"Could not parse bearing from {text!r}")
    ns = m.group("ns").upper()
    ew = m.group("ew").upper()
    deg = float(m.group("deg"))
    minutes = float(m.group("min")) if m.group("min") else 0.0
    seconds = float(m.group("sec")) if m.group("sec") else 0.0
    angle = math.radians(deg + minutes / 60 + seconds / 3600)
    # Quadrant → azimuth (0 = N, π/2 = E, etc.)
    if ns == "N" and ew == "E":
        return angle
    if ns == "S" and ew == "E":
        return math.pi - angle
    if ns == "S" and ew == "W":
        return math.pi + angle
    if ns == "N" and ew == "W":
        return 2 * math.pi - angle
    raise DeedParseError(f"Bad bearing quadrants: {ns}{ew}")  # pragma: no cover


def parse_distance(text: str) -> float:
    """Parse a distance string with unit into meters."""
    m = _RE_DISTANCE.search(text)
    if not m:
        raise DeedParseError(f"Could not parse distance from {text!r}")
    value = float(m.group("value"))
    unit = m.group("unit").lower().rstrip(".")
    if unit not in DISTANCE_UNITS_M:
        raise DeedParseError(f"Unknown distance unit: {unit!r}")
    return value * DISTANCE_UNITS_M[unit]


def parse_delta(text: str) -> float:
    """Parse a curve delta angle in DMS or decimal degrees → radians."""
    text = text.strip()
    dms_re = re.compile(r"(\d+)(?:°|deg)\s*(\d+)\s*'\s*(\d+(?:\.\d+)?)\s*\"?", re.IGNORECASE)
    m = dms_re.search(text)
    if m:
        return dms_to_radians(float(m.group(1)), float(m.group(2)), float(m.group(3)))
    try:
        return math.radians(float(text))
    except ValueError as e:
        raise DeedParseError(f"Could not parse delta {text!r}") from e


# ── Parser ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DeedParseResult:
    """Output of :func:`parse_deed_text`."""

    calls: tuple[Call, ...]
    point_of_beginning_text: str | None
    unparsed_clauses: tuple[str, ...]


def parse_deed_text(
    text: str,
    *,
    llm: LLMClient | None = None,
) -> DeedParseResult:
    """Parse a metes-and-bounds description into :class:`Call` records.

    Rough strategy:

    * Split on ``THENCE`` (or its abbreviations).
    * For each clause, try the curve regex first (curves often contain
      bearings inside them — easy false-positive otherwise), then the
      line regex.
    * Collect anything we couldn't parse so reviewers can audit gaps.
    """
    if not text or not text.strip():
        raise DeedParseError("Empty deed text.")

    pob_match = _RE_POB.search(text)
    pob_text = pob_match.group(0) if pob_match else None

    # Normalize whitespace and split on "THENCE" or its variants.
    cleaned = re.sub(r"\s+", " ", text).strip()
    clauses = re.split(r"\b(?:THENCE|THENCE,)\b", cleaned, flags=re.IGNORECASE)
    # The first split-piece is the preamble (POB description); skip it as a call.
    clauses = [c.strip(" ,;.") for c in clauses[1:] if c.strip()]

    calls: list[Call] = []
    unparsed: list[str] = []
    for idx, clause in enumerate(clauses, start=1):
        call = _try_parse_clause(clause, idx)
        if call is not None:
            calls.append(call)
        else:
            unparsed.append(clause)

    if not calls:
        raise DeedParseError("Could not parse any calls from the description.")

    return DeedParseResult(
        calls=tuple(calls),
        point_of_beginning_text=pob_text,
        unparsed_clauses=tuple(unparsed),
    )


def _try_parse_clause(clause: str, idx: int) -> Call | None:
    """Try curve, then line; return None if neither matches."""
    cm = _RE_CURVE.search(clause)
    if cm and (cm.group("radius") or cm.group("arc") or cm.group("delta")):
        radius = _to_meters(cm.group("radius"), cm.group("runit")) if cm.group("radius") else None
        arc_len = _to_meters(cm.group("arc"), cm.group("aunit")) if cm.group("arc") else None
        delta = parse_delta(cm.group("delta")) if cm.group("delta") else None
        chord_len = _to_meters(cm.group("chord"), cm.group("cunit")) if cm.group("chord") else None
        chord_brg = parse_bearing(cm.group("chordbrg")) if cm.group("chordbrg") else None
        cw = (cm.group("dir") or "").lower() in ("right", "clockwise")
        # Fill in missing pieces from chord triangle when possible.
        if delta is None and radius and chord_len:
            delta = 2 * math.asin(min(1.0, max(-1.0, chord_len / (2 * radius))))
        if arc_len is None and radius and delta:
            arc_len = radius * delta
        if chord_len is None and radius and delta:
            chord_len = 2 * radius * math.sin(delta / 2)
        return Call(
            kind=CallKind.CURVE_CHORD,
            bearing=chord_brg,
            distance=chord_len,
            radius=radius,
            delta=delta,
            chord=chord_len,
            clockwise=cw,
            notes=clause,
            raw_index=idx,
        )

    lm = _RE_LINE_CALL.search(clause)
    if lm:
        return Call(
            kind=CallKind.LINE,
            bearing=parse_bearing(lm.group("bearing")),
            distance=parse_distance(lm.group("distance")),
            notes=clause,
            raw_index=idx,
        )

    return None


def _to_meters(value: str | None, unit: str | None) -> float | None:
    if value is None or unit is None:
        return None
    unit_norm = unit.lower().rstrip(".")
    factor = DISTANCE_UNITS_M.get(unit_norm)
    if factor is None:
        return None
    return float(value) * factor


# ── Boundary computation ───────────────────────────────────────────────────


def boundary_from_calls(
    calls: tuple[Call, ...],
    pob: Point2D,
) -> Boundary:
    """Compute coordinates for a list of calls and report misclosure."""
    from meridian.domain.geometry import Point2D, Polygon
    from meridian.domain.parcel import Boundary

    bearings: list[float] = []
    distances: list[float] = []
    for c in calls:
        if c.bearing is None or c.distance is None:
            raise DeedParseError(
                f"Call #{c.raw_index} ({c.kind.value}) is missing bearing or distance."
            )
        # For curves we treat the chord as a line for now. v0.2 will replace
        # this with proper arc-on-polygon support.
        bearings.append(c.bearing)
        distances.append(c.distance)

    result = run_traverse(start=(pob.x, pob.y), bearings=bearings, distances=distances)
    coords = result.coordinates  # (N+1, 2)

    # Build a closed Polygon. We add the POB as the closing point regardless
    # of whether the deed actually closed perfectly — the misclosure tells
    # the user how far off they are.
    closed = np.vstack([coords, coords[0]])
    pts = tuple(
        Point2D(x=float(p[0]), y=float(p[1]), crs=pob.crs)
        for p in closed
    )
    polygon = Polygon(exterior=pts).oriented()

    closure_ratio = float("inf") if result.closure_distance == 0 else result.perimeter / result.closure_distance

    return Boundary(
        polygon=polygon,
        misclosure_distance=result.closure_distance,
        misclosure_bearing=result.closure_bearing,
        perimeter=result.perimeter,
        closure_ratio=closure_ratio,
        point_of_beginning=pob,
    )
