"""Subdivision plat parser + analyzer.

A recorded subdivision plat divides a parent tract into:

* **Lots** — buildable parcels, numbered.
* **Blocks** — groups of lots typically separated by streets.
* **Streets / right-of-way** — polylines for road centerlines, often
  with width.
* **Common areas** — open space, drainage detention, HOA-owned tracts.
* **Easements** — utility, drainage, access (handled by
  :mod:`meridian.jurisdictions.easement`).

This module accepts unstructured plat text (typically the
"Description" pages of a subdivision plat in the county records) and
produces a :class:`Subdivision` with each lot, block, street, and
common area parsed into structured records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from meridian.pipelines.deed_to_polygon import DeedParseResult, parse_deed_text

if TYPE_CHECKING:
    pass


class FeatureKind(str, Enum):
    LOT = "lot"
    BLOCK = "block"
    STREET = "street"
    EASEMENT = "easement"
    COMMON_AREA = "common_area"
    DRAINAGE = "drainage"
    PARK = "park"
    FUTURE_DEV = "future_dev"


@dataclass(frozen=True, slots=True)
class Lot:
    number: str                             # "1", "12A"
    block: str | None                       # "B" or "Block 2"
    description_text: str
    parsed: DeedParseResult | None = None
    area_m2: float | None = None
    address: str | None = None
    setback_front_m: float | None = None
    setback_side_m: float | None = None
    setback_rear_m: float | None = None


@dataclass(frozen=True, slots=True)
class Block:
    name: str
    lot_count: int
    description_text: str | None = None


@dataclass(frozen=True, slots=True)
class Street:
    name: str
    width_m: float | None = None
    description_text: str | None = None


@dataclass(frozen=True, slots=True)
class CommonArea:
    label: str
    kind: FeatureKind
    description_text: str | None = None


@dataclass(frozen=True, slots=True)
class Subdivision:
    name: str
    recording_reference: str | None
    lots: tuple[Lot, ...]
    blocks: tuple[Block, ...]
    streets: tuple[Street, ...]
    common_areas: tuple[CommonArea, ...]
    raw_text: str = ""


# ── Patterns ───────────────────────────────────────────────────────────────


_LOT_RE = re.compile(
    r"""
    \bLot\s+(?P<num>\d+[A-Z]?)\b
    (?:\s*,\s*Block\s+(?P<block>\w+))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_BLOCK_RE = re.compile(r"\bBlock\s+(\w+)\b", re.IGNORECASE)

_STREET_RE = re.compile(
    r"""
    \b(
        [A-Z][a-z]+(?:\s+[A-Z][a-z]+)*
    )\s+(Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Road|Rd\.?|Way|Court|Ct\.?|Place|Pl\.?|Circle|Cir\.?|Parkway|Pkwy\.?|Trail|Trl\.?)
    """,
    re.VERBOSE,
)

_RECORDING_RE = re.compile(
    r"""(?:recorded\s+in\s+|inst\.\s*no\.?\s*|cabinet\s+|slide\s+|volume\s+|vol\.?\s*|book\s+)
        ([A-Z0-9./\-, ]+?)
        (?:\s+(?:of|page|pg\.?))""",
    re.IGNORECASE | re.VERBOSE,
)

_SUBDIVISION_NAME_RE = re.compile(
    r"""(?:Subdivision\s+of|known\s+as|plat\s+of)\s+
        (?P<name>[A-Z][\w\s&'\-,]+?)
        (?:\s*,?\s*(?:as\s+recorded|recorded|according))""",
    re.IGNORECASE | re.VERBOSE,
)


# ── Parser ─────────────────────────────────────────────────────────────────


def parse_subdivision(text: str, *, name: str | None = None) -> Subdivision:
    """Parse a subdivision plat description into structured records."""
    derived_name = name
    if derived_name is None:
        m = _SUBDIVISION_NAME_RE.search(text)
        derived_name = m.group("name").strip() if m else "Unnamed Subdivision"

    rec_match = _RECORDING_RE.search(text)
    recording = rec_match.group(1).strip() if rec_match else None

    lots = _parse_lots(text)
    blocks = _parse_blocks(text, lots)
    streets = _parse_streets(text)
    common_areas = _parse_common_areas(text)

    return Subdivision(
        name=derived_name,
        recording_reference=recording,
        lots=lots,
        blocks=blocks,
        streets=streets,
        common_areas=common_areas,
        raw_text=text,
    )


def _parse_lots(text: str) -> tuple[Lot, ...]:
    """Extract Lot ## (, Block X) references with surrounding sentence."""
    lots: list[Lot] = []
    seen: set[tuple[str, str | None]] = set()
    # Walk sentences; for each, extract any Lot ## references.
    for sentence in _split_sentences(text):
        for m in _LOT_RE.finditer(sentence):
            num = m.group("num")
            block = m.group("block")
            key = (num, block)
            if key in seen:
                continue
            seen.add(key)
            # Try to parse this sentence as a metes-and-bounds clause.
            parsed = None
            try:
                parsed = parse_deed_text(sentence)
            except Exception:
                parsed = None
            lots.append(
                Lot(
                    number=num,
                    block=block,
                    description_text=sentence.strip(),
                    parsed=parsed,
                )
            )
    return tuple(lots)


def _parse_blocks(text: str, lots: tuple[Lot, ...]) -> tuple[Block, ...]:
    block_names: dict[str, int] = {}
    for m in _BLOCK_RE.finditer(text):
        block_names.setdefault(m.group(1), 0)
    # Count lots per block.
    for lot in lots:
        if lot.block:
            block_names[lot.block] = block_names.get(lot.block, 0) + 1
    return tuple(
        Block(name=name, lot_count=count) for name, count in sorted(block_names.items())
    )


def _parse_streets(text: str) -> tuple[Street, ...]:
    seen: set[str] = set()
    out: list[Street] = []
    for m in _STREET_RE.finditer(text):
        full = (m.group(1).strip() + " " + m.group(2).strip()).rstrip(".")
        # Skip false-positives — single-word names lower-cased are unlikely.
        if full.lower() in seen or len(full.split()) < 2:
            continue
        seen.add(full.lower())
        # Try to extract a width from the surrounding context.
        width = _find_width_near(text, m.start(), m.end())
        out.append(Street(name=full, width_m=width))
    return tuple(out)


def _parse_common_areas(text: str) -> tuple[CommonArea, ...]:
    rules = (
        ("Common Area", FeatureKind.COMMON_AREA),
        ("Open Space", FeatureKind.COMMON_AREA),
        ("Detention Pond", FeatureKind.DRAINAGE),
        ("Drainage Easement", FeatureKind.DRAINAGE),
        ("Park", FeatureKind.PARK),
        ("HOA Tract", FeatureKind.COMMON_AREA),
        ("Future Development", FeatureKind.FUTURE_DEV),
    )
    out: list[CommonArea] = []
    for label, kind in rules:
        if re.search(rf"\b{re.escape(label)}\b", text, re.IGNORECASE):
            out.append(CommonArea(label=label, kind=kind))
    return tuple(out)


# ── helpers ────────────────────────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", cleaned)
    return [p for p in parts if len(p.split()) >= 3]


_WIDTH_RE = re.compile(
    r"""(?P<value>\d+(?:\.\d+)?)\s*[-\s]*
        (?P<unit>(?:foot|feet|ft|meter|metre|meters|metres|m)\b)
        \s*(?:wide|in\s+width)?""",
    re.IGNORECASE | re.VERBOSE,
)


def _find_width_near(text: str, start: int, end: int) -> float | None:
    """Look for ``50-foot wide`` immediately after the street name.

    Real plats put the width annotation right after the street name —
    "Sunset Ridge Drive is a 60-foot wide right-of-way." Searching
    backward picks up unrelated dimensions from the previous sentence.
    """
    # 120-char forward window only — width follows the name in standard syntax.
    window = text[end: end + 120]
    m = _WIDTH_RE.search(window)
    if not m:
        return None
    value = float(m.group("value"))
    unit = m.group("unit").lower()
    if "m" in unit and "f" not in unit:
        return value
    return value * 0.3048


# ── Report ─────────────────────────────────────────────────────────────────


def write_subdivision_report_html(sub: Subdivision, output_path) -> int:
    rows_lots = "".join(
        f"<tr><td>{lot.number}</td><td>{lot.block or '—'}</td>"
        f"<td>{(lot.description_text or '')[:140]}…</td></tr>"
        for lot in sub.lots
    )
    rows_blocks = "".join(
        f"<tr><td>{b.name}</td><td>{b.lot_count}</td></tr>"
        for b in sub.blocks
    )
    rows_streets = "".join(
        f"<tr><td>{s.name}</td><td>{f'{s.width_m:.1f} m' if s.width_m else '—'}</td></tr>"
        for s in sub.streets
    )
    rows_common = "".join(
        f"<tr><td>{c.label}</td><td>{c.kind.value}</td></tr>"
        for c in sub.common_areas
    )
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>Subdivision: {sub.name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }}
h1 {{ font-size: 20px; color: #1f3b73; margin: 0 0 4px 0; }}
h2 {{ font-size: 14px; color: #1f3b73; margin: 18px 0 6px 0; border-bottom: 1px solid #d3dae8; padding-bottom: 4px; }}
.subtitle {{ color: #5a6a82; font-size: 12px; margin-bottom: 16px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #d3dae8; padding: 6px 10px; text-align: left; }}
th {{ background: #1f3b73; color: white; font-weight: 600; }}
tr:nth-child(even) td {{ background: #f7f9fd; }}
</style></head><body>
<h1>{sub.name}</h1>
<div class="subtitle">Recorded: {sub.recording_reference or '—'} · {len(sub.lots)} lots · {len(sub.blocks)} blocks · {len(sub.streets)} streets · {len(sub.common_areas)} common areas</div>
<h2>Lots</h2>
<table><thead><tr><th>Lot</th><th>Block</th><th>Description (truncated)</th></tr></thead><tbody>{rows_lots or '<tr><td colspan="3"><em>None.</em></td></tr>'}</tbody></table>
<h2>Blocks</h2>
<table><thead><tr><th>Block</th><th>Lots</th></tr></thead><tbody>{rows_blocks or '<tr><td colspan="2"><em>None.</em></td></tr>'}</tbody></table>
<h2>Streets</h2>
<table><thead><tr><th>Name</th><th>Width</th></tr></thead><tbody>{rows_streets or '<tr><td colspan="2"><em>None.</em></td></tr>'}</tbody></table>
<h2>Common areas</h2>
<table><thead><tr><th>Label</th><th>Kind</th></tr></thead><tbody>{rows_common or '<tr><td colspan="2"><em>None.</em></td></tr>'}</tbody></table>
</body></html>"""
    if hasattr(output_path, "write_text"):
        output_path.write_text(body, encoding="utf-8")
        return output_path.stat().st_size
    return 0
