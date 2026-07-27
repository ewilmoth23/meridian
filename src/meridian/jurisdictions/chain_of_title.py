"""Chain-of-title reconstruction with HTML timeline.

Given a list of recorded deeds, build a directed grantor → grantee chain
across time. Detect six classes of defect:

1. **Wild deed** — a deed conveying *out of* a grantor who never appears
   as a grantee in the chain (i.e. they didn't have title to give).
2. **Gap** — recording dates leave a multi-year window where ownership is
   unaccounted for.
3. **Fork** — a grantor conveys to two different grantees (one is invalid).
4. **Date inversion** — a deed has a recording date earlier than its
   grantor's most recent acquisition.
5. **Self-conveyance** — grantor == grantee (suspicious; sometimes legit).
6. **Duplicate** — same instrument number twice.

Output: an :class:`HTML` timeline with color-coded defects suitable for
an examiner's report.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from meridian.domain.deed import Deed, PartyRole


class DefectKind(str, Enum):
    WILD_DEED = "wild_deed"
    GAP = "gap"
    FORK = "fork"
    DATE_INVERSION = "date_inversion"
    SELF_CONVEYANCE = "self_conveyance"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class TitleLink:
    """One hop in a chain: grantor → grantee on a recording date."""

    deed_id: str
    grantor: str
    grantee: str
    recorded_date: dt.date | None
    instrument_number: str | None = None
    book: str | None = None
    page: str | None = None
    defects: tuple[TitleDefect, ...] = ()


@dataclass(frozen=True, slots=True)
class TitleDefect:
    kind: DefectKind
    description: str
    related_deed_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChainOfTitle:
    parcel_id: str
    links: tuple[TitleLink, ...]
    defects: tuple[TitleDefect, ...]


_NORMAL_RE = re.compile(r"\s+")
_SUFFIX_RE = re.compile(r"\b(et\s+ux\.?|et\s+vir\.?|et\s+al\.?|jr\.?|sr\.?|iii?|iv|llc|inc\.?|corp\.?)\b", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and corporate / spousal suffixes."""
    s = name.lower().strip()
    s = re.sub(r"[,.]", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    s = _NORMAL_RE.sub(" ", s)
    return s.strip()


def build_chain(parcel_id: str, deeds: list[Deed]) -> ChainOfTitle:
    """Build a chain of title from a list of deeds."""
    links: list[TitleLink] = []
    seen_instruments: set[str] = set()
    duplicate_defects: list[TitleDefect] = []

    for deed in deeds:
        grantors = [p.name for p in deed.parties if p.role == PartyRole.GRANTOR]
        grantees = [p.name for p in deed.parties if p.role == PartyRole.GRANTEE]
        if not grantors or not grantees:
            continue
        # One link per grantor x grantee pair (rare but valid).
        for g in grantors:
            for ge in grantees:
                instrument = deed.recording.instrument_number or f"{deed.recording.book}/{deed.recording.page}"
                if instrument and instrument in seen_instruments:
                    duplicate_defects.append(
                        TitleDefect(
                            kind=DefectKind.DUPLICATE,
                            description=f"Duplicate instrument number {instrument}",
                            related_deed_ids=(deed.id,),
                        )
                    )
                if instrument:
                    seen_instruments.add(instrument)
                links.append(
                    TitleLink(
                        deed_id=deed.id,
                        grantor=g,
                        grantee=ge,
                        recorded_date=deed.recording.recorded_date,
                        instrument_number=deed.recording.instrument_number,
                        book=deed.recording.book,
                        page=deed.recording.page,
                    )
                )

    # Sort by recording date (None last). Stable sort preserves input order.
    links.sort(key=lambda link: (link.recorded_date or dt.date(9999, 12, 31)))

    defects: list[TitleDefect] = list(duplicate_defects)

    # ── Wild deed + last-known-owner detection ─────────────────────────────
    # Maintain the set of names known to have been granted *into* the chain.
    # A grantor not in that set yet is "wild". We seed with the very first
    # grantor (assumed root patent / GLO conveyance).
    known: set[str] = set()
    if links:
        known.add(normalize_name(links[0].grantor))
    last_acquired: dict[str, dt.date | None] = {}

    for link in links:
        g_norm = normalize_name(link.grantor)
        ge_norm = normalize_name(link.grantee)

        if g_norm == ge_norm:
            defects.append(
                TitleDefect(
                    kind=DefectKind.SELF_CONVEYANCE,
                    description=f"{link.grantor} conveys to themself ({link.deed_id})",
                    related_deed_ids=(link.deed_id,),
                )
            )

        if g_norm not in known:
            defects.append(
                TitleDefect(
                    kind=DefectKind.WILD_DEED,
                    description=(
                        f"Grantor {link.grantor!r} never appears as a grantee "
                        f"earlier in the chain (deed {link.deed_id})"
                    ),
                    related_deed_ids=(link.deed_id,),
                )
            )

        last = last_acquired.get(g_norm)
        if last and link.recorded_date and link.recorded_date < last:
            defects.append(
                TitleDefect(
                    kind=DefectKind.DATE_INVERSION,
                    description=(
                        f"{link.grantor} conveys on {link.recorded_date} but acquired on {last}"
                    ),
                    related_deed_ids=(link.deed_id,),
                )
            )

        known.add(ge_norm)
        last_acquired[ge_norm] = link.recorded_date

    # ── Forks ──────────────────────────────────────────────────────────────
    by_grantor: dict[str, list[TitleLink]] = defaultdict(list)
    for link in links:
        by_grantor[normalize_name(link.grantor)].append(link)
    for grantor, grantor_links in by_grantor.items():
        if len(grantor_links) <= 1:
            continue
        # Sort by recorded date — only flag if they convey to *different* grantees
        # both *before* selling out completely (i.e. both have unsold portions).
        grantees: set[str] = {normalize_name(link.grantee) for link in grantor_links}
        if len(grantees) > 1:
            defects.append(
                TitleDefect(
                    kind=DefectKind.FORK,
                    description=(
                        f"{grantor} conveys to multiple grantees: "
                        + ", ".join(sorted(grantees))
                    ),
                    related_deed_ids=tuple(link.deed_id for link in grantor_links),
                )
            )

    # ── Gaps (look for unusually long unaccounted-for holes) ─────────────
    # 30-year threshold avoids flagging the typical 25-year ownership tenure
    # while still catching the multi-generation breaks that signal lost deeds.
    import itertools as _it
    gap_days = 365 * 30
    for prev, link in _it.pairwise(links):
        if prev.recorded_date is None or link.recorded_date is None:
            continue
        delta = (link.recorded_date - prev.recorded_date).days
        if delta > gap_days:
            defects.append(
                TitleDefect(
                    kind=DefectKind.GAP,
                    description=(
                        f"{delta // 365}-year gap between {prev.recorded_date} "
                        f"and {link.recorded_date}"
                    ),
                    related_deed_ids=(prev.deed_id, link.deed_id),
                )
            )

    return ChainOfTitle(parcel_id=parcel_id, links=tuple(links), defects=tuple(defects))


# ── HTML timeline ───────────────────────────────────────────────────────────


def write_chain_html(chain: ChainOfTitle, output_path) -> int:
    """Render the chain as a vertical timeline with color-coded defects."""
    deed_to_defects: dict[str, list[TitleDefect]] = defaultdict(list)
    for d in chain.defects:
        for did in d.related_deed_ids:
            deed_to_defects[did].append(d)

    items: list[str] = []
    for link in chain.links:
        defects_here = deed_to_defects.get(link.deed_id, [])
        sev_color = "#0a8a3a"
        sev_label = ""
        if defects_here:
            sev_color = "#c33"
            sev_label = " · ".join(d.kind.value.replace("_", " ") for d in defects_here)
        date = link.recorded_date.isoformat() if link.recorded_date else "—"
        rec = link.instrument_number or (
            f"Bk {link.book}, Pg {link.page}" if link.book else "—"
        )
        items.append(
            f"""<li style="border-left:4px solid {sev_color};padding:8px 14px;margin-bottom:8px;background:#f7f9fd">
  <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;color:#5a6a82">{html.escape(date)} · {html.escape(rec)}</div>
  <div style="font-size:13px;margin-top:2px"><b>{html.escape(link.grantor)}</b> → {html.escape(link.grantee)}</div>
  <div style="font-size:11px;color:{sev_color};margin-top:4px;font-weight:600">{html.escape(sev_label)}</div>
</li>"""
        )

    defect_blocks: list[str] = []
    for d in chain.defects:
        defect_blocks.append(
            f"<li><b>{html.escape(d.kind.value)}</b>: {html.escape(d.description)}</li>"
        )

    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>Chain of Title — {html.escape(chain.parcel_id)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; max-width: 760px; }}
h1 {{ font-size: 20px; color: #1f3b73; margin: 0 0 4px 0; }}
.subtitle {{ color: #5a6a82; font-size: 12px; margin-bottom: 16px; }}
ol, ul {{ list-style: none; padding: 0; }}
.section-title {{ font-size: 14px; color: #1f3b73; margin: 18px 0 8px 0; border-bottom: 1px solid #d3dae8; padding-bottom: 4px; }}
</style></head><body>
<h1>Chain of Title</h1>
<div class="subtitle">Parcel: {html.escape(chain.parcel_id)} · {len(chain.links)} link{'' if len(chain.links) == 1 else 's'} · {len(chain.defects)} defect{'' if len(chain.defects) == 1 else 's'}</div>
<div class="section-title">Timeline</div>
<ol>{''.join(items) or '<li><em>No links.</em></li>'}</ol>
<div class="section-title">Defect summary</div>
<ul>{''.join(defect_blocks) or '<li><em>None detected.</em></li>'}</ul>
</body></html>"""
    if hasattr(output_path, "write_text"):
        output_path.write_text(body, encoding="utf-8")
        return output_path.stat().st_size
    return 0
