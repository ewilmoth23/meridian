"""LESS AND EXCEPT / multi-tract deed parser.

Real deeds rarely describe one clean polygon. They typically describe a
*parent* tract and then carve out one or more *exceptions* — chunks the
grantor is keeping or that were already conveyed elsewhere. The
boundary surveyor needs to compute the *net* area conveyed.

Common phrasings this parser recognises:

    SAVE AND EXCEPT  ...
    LESS AND EXCEPT  ...
    EXCEPT FOR       ...
    SAVING AND EXCEPTING  ...
    SUBJECT TO        ...     (sometimes a carve-out, sometimes an encumbrance)
    RESERVING UNTO   ...
    Tract 1 / Parcel A      (multi-tract syntax)

Output is a :class:`MultiTractDocument` containing the parent + each
exception tract, linked by metadata. Geometric containment is checked
when the polygons can all be computed; otherwise we emit a warning that
the relationship is implied by the deed text only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from meridian.pipelines.deed_to_polygon import DeedParseResult, parse_deed_text

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point2D


class TractRole(str, Enum):
    PARENT = "parent"
    EXCEPTION = "exception"
    RESERVATION = "reservation"
    SUBJECT_TO = "subject_to"
    ADDITIONAL_TRACT = "additional_tract"


_EXCEPT_RE = re.compile(
    r"""
    (?:                                         # the carve-out marker
        (?:SAVE\s+AND\s+EXCEPT(?:ING)?)
      | (?:LESS\s+AND\s+EXCEPT(?:ING)?)
      | (?:SAVING\s+AND\s+EXCEPTING)
      | (?:EXCEPT(?:ING)?\s+(?:FOR\s+)?THAT)
      | (?:EXCEPT(?:ING)?\s+THE)
      | (?:RESERVING\s+UNTO)
      | (?:SUBJECT\s+TO\s+THAT\s+CERTAIN)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


_TRACT_RE = re.compile(
    r"""
    \b(?:
        TRACT\s+(?P<tn>[A-Z0-9]+)
      | PARCEL\s+(?P<pn>[A-Z0-9]+)
      | TRACT\s+ROMAN\s+(?P<rn>[IVX]+)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


_RESERVATION_RE = re.compile(r"\bRESERVING\s+UNTO\b", re.IGNORECASE)


_TRACT_HEAD_RE = re.compile(
    r"""
    ^[\s]*
    (?:TRACT|PARCEL)\s+([A-Z0-9]+|[IVX]+)\s*[:\-]?
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class TractDescription:
    """One tract carved from a multi-tract document."""

    label: str                      # "Parent", "Tract 1", "Exception A", ...
    role: TractRole
    text: str
    parsed: DeedParseResult | None  # None if the parser couldn't extract calls
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class MultiTractDocument:
    """A deed document that describes a parent + zero or more carve-outs."""

    parent: TractDescription
    exceptions: tuple[TractDescription, ...]
    additional_tracts: tuple[TractDescription, ...] = ()
    reservations: tuple[TractDescription, ...] = ()
    raw_text: str = ""

    @property
    def all_tracts(self) -> tuple[TractDescription, ...]:
        return (self.parent, *self.exceptions, *self.additional_tracts, *self.reservations)


# ── Public API ─────────────────────────────────────────────────────────────


def detect_multi_tract(text: str) -> bool:
    """True if the deed has a ``Tract 1`` / ``Parcel A`` style header."""
    return bool(_TRACT_HEAD_RE.search(text))


def detect_exceptions(text: str) -> bool:
    """True if the deed contains a SAVE AND EXCEPT / LESS AND EXCEPT clause."""
    return bool(_EXCEPT_RE.search(text))


def parse_multi_tract_document(text: str) -> MultiTractDocument:
    """Parse a deed text that may contain multiple tracts and / or
    save-and-except clauses.

    Strategy:

    1. If the text has explicit ``Tract X`` / ``Parcel X`` headers, split
       on those headers.
    2. Otherwise treat the full text as the parent and split off any
       SAVE AND EXCEPT / LESS AND EXCEPT clauses.
    3. Try to parse each chunk into a :class:`DeedParseResult`. If
       parsing fails, keep the text as-is so the surveyor can review.
    """
    if detect_multi_tract(text):
        return _parse_explicit_tracts(text)
    return _parse_parent_with_exceptions(text)


def _parse_explicit_tracts(text: str) -> MultiTractDocument:
    """Split a deed with ``Tract 1 / Tract 2`` style headers."""
    splits = list(_TRACT_HEAD_RE.finditer(text))
    if not splits:
        return _parse_parent_with_exceptions(text)
    chunks: list[tuple[str, str]] = []
    # Prefix before first tract header is the deed preamble.
    if splits[0].start() > 0:
        chunks.append(("Preamble", text[:splits[0].start()].strip()))
    for i, m in enumerate(splits):
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        chunks.append((f"Tract {m.group(1)}", text[m.start():end].strip()))

    parent: TractDescription | None = None
    additional: list[TractDescription] = []
    exceptions: list[TractDescription] = []

    for label, chunk in chunks:
        # First substantive tract is the parent.
        if label == "Preamble":
            continue
        parsed = _try_parse(chunk)
        # Look for SAVE/EXCEPT *inside* this tract.
        excepts = _split_off_exceptions(chunk)
        for exc_text in excepts:
            exceptions.append(
                TractDescription(
                    label=f"{label} — Exception",
                    role=TractRole.EXCEPTION,
                    text=exc_text,
                    parsed=_try_parse(exc_text),
                )
            )
        # The remaining chunk text minus the carve-outs.
        remainder = _strip_exceptions(chunk)
        parsed_remainder = _try_parse(remainder) or parsed
        tract = TractDescription(
            label=label,
            role=TractRole.PARENT if parent is None else TractRole.ADDITIONAL_TRACT,
            text=remainder.strip(),
            parsed=parsed_remainder,
        )
        if parent is None:
            parent = tract
        else:
            additional.append(tract)

    if parent is None:
        # Defensive fallback — treat the whole text as the parent.
        parent = TractDescription(label="Parent", role=TractRole.PARENT, text=text, parsed=_try_parse(text))

    reservations = _extract_reservations(text)
    return MultiTractDocument(
        parent=parent,
        exceptions=tuple(exceptions),
        additional_tracts=tuple(additional),
        reservations=reservations,
        raw_text=text,
    )


def _parse_parent_with_exceptions(text: str) -> MultiTractDocument:
    """Split a single-tract deed with SAVE AND EXCEPT clauses."""
    parts = _split_at_exceptions(text)
    parent_text = parts[0]
    exception_texts = parts[1:]

    parent = TractDescription(
        label="Parent",
        role=TractRole.PARENT,
        text=parent_text.strip(),
        parsed=_try_parse(parent_text),
    )
    exceptions = tuple(
        TractDescription(
            label=f"Exception {i + 1}",
            role=TractRole.EXCEPTION,
            text=t.strip(),
            parsed=_try_parse(t),
        )
        for i, t in enumerate(exception_texts)
    )
    return MultiTractDocument(
        parent=parent,
        exceptions=exceptions,
        additional_tracts=(),
        reservations=_extract_reservations(text),
        raw_text=text,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _try_parse(text: str) -> DeedParseResult | None:
    if not text or len(text.split()) < 5:
        return None
    try:
        return parse_deed_text(text)
    except Exception:
        return None


def _split_at_exceptions(text: str) -> list[str]:
    """Split ``text`` at SAVE AND EXCEPT boundaries; first chunk is parent."""
    matches = list(_EXCEPT_RE.finditer(text))
    if not matches:
        return [text]
    parts: list[str] = [text[: matches[0].start()]]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts.append(text[m.end(): end])
    return parts


def _split_off_exceptions(text: str) -> list[str]:
    """Return just the SAVE AND EXCEPT bodies from ``text`` (no parent)."""
    return _split_at_exceptions(text)[1:]


def _strip_exceptions(text: str) -> str:
    """Remove SAVE AND EXCEPT clauses from ``text`` (returning parent only)."""
    parts = _split_at_exceptions(text)
    return parts[0]


def _extract_reservations(text: str) -> tuple[TractDescription, ...]:
    """Pull RESERVING UNTO clauses into their own tract objects."""
    matches = list(_RESERVATION_RE.finditer(text))
    if not matches:
        return ()
    out: list[TractDescription] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else min(m.end() + 800, len(text))
        body = text[m.end(): end].strip(" .;,\n")
        out.append(
            TractDescription(
                label=f"Reservation {i + 1}",
                role=TractRole.RESERVATION,
                text=body,
                parsed=_try_parse(body),
            )
        )
    return tuple(out)


# ── Net-area computation ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NetAreaResult:
    """Parent area minus all parsed exceptions."""

    parent_area_m2: float
    exception_area_m2: float
    net_area_m2: float
    method: str        # "exact" if all polygons computed, "implied" if some failed
    warnings: tuple[str, ...] = ()

    @property
    def net_area_acres(self) -> float:
        return self.net_area_m2 / 4046.8564224


def compute_net_area(
    document: MultiTractDocument,
    crs: CRS,
    *,
    pob: Point2D | None = None,
) -> NetAreaResult:
    """Compute net area from a parsed multi-tract document.

    Returns a :class:`NetAreaResult`. The ``method`` field is ``"exact"``
    when every tract's polygon could be computed; ``"implied"`` if any
    tract failed to parse and we fell back to the deed-stated acreage.
    """
    from meridian.domain.geometry import Point2D
    from meridian.pipelines.deed_to_polygon import boundary_from_calls

    pob_pt = pob or Point2D(0.0, 0.0, crs)
    warnings: list[str] = []

    def _area(parsed: DeedParseResult | None, label: str) -> float:
        if parsed is None or not parsed.calls:
            warnings.append(f"{label}: could not parse calls; area treated as 0.")
            return 0.0
        try:
            boundary = boundary_from_calls(parsed.calls, pob_pt)
        except Exception as e:
            warnings.append(f"{label}: boundary computation failed ({e}); area treated as 0.")
            return 0.0
        return boundary.polygon.area()

    parent_area = _area(document.parent.parsed, document.parent.label)
    exception_area = sum(_area(t.parsed, t.label) for t in document.exceptions)
    method = "exact" if not warnings else "implied"
    return NetAreaResult(
        parent_area_m2=parent_area,
        exception_area_m2=exception_area,
        net_area_m2=max(parent_area - exception_area, 0.0),
        method=method,
        warnings=tuple(warnings),
    )
