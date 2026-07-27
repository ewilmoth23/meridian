"""Title commitment parser — Schedule A / B-I / B-II.

A title commitment is the document a title insurer issues during a real
estate transaction. It has three schedules:

* **Schedule A** — what's being insured: effective date, proposed insured
  party, estate type, vested owner, legal description, premium.
* **Schedule B-I (Requirements)** — things that must happen before
  policy issuance: pay off mortgage, deliver deed, satisfy judgments,
  obtain survey, etc.
* **Schedule B-II (Exceptions)** — encumbrances the policy will *not*
  cover: easements, CC&Rs, mineral reservations, mortgages of record,
  liens, leases.

This module accepts unstructured text (typically OCR'd) and returns a
structured :class:`TitleCommitment`. The classifier categorises each
B-I / B-II item by type so reviewers can sort by risk.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import Enum


class EstateType(str, Enum):
    FEE_SIMPLE = "fee_simple"
    LEASEHOLD = "leasehold"
    EASEMENT = "easement"
    LIFE_ESTATE = "life_estate"
    REMAINDER = "remainder"
    UNKNOWN = "unknown"


class RequirementType(str, Enum):
    MORTGAGE_PAYOFF = "mortgage_payoff"
    DEED_DELIVERY = "deed_delivery"
    JUDGMENT_RELEASE = "judgment_release"
    LIEN_RELEASE = "lien_release"
    SURVEY_REQUIRED = "survey_required"
    AFFIDAVIT = "affidavit"
    PROBATE = "probate"
    TAX_PAYMENT = "tax_payment"
    HOA_LETTER = "hoa_letter"
    ENTITY_AUTHORITY = "entity_authority"
    POWER_OF_ATTORNEY = "power_of_attorney"
    CORRECTION_DEED = "correction_deed"
    ENCROACHMENT = "encroachment"
    OTHER = "other"


class ExceptionType(str, Enum):
    EASEMENT = "easement"
    UTILITY_EASEMENT = "utility_easement"
    ACCESS_EASEMENT = "access_easement"
    DRAINAGE_EASEMENT = "drainage_easement"
    CONSERVATION_EASEMENT = "conservation_easement"
    CCR = "ccr"
    HOA = "hoa"
    MINERAL_RESERVATION = "mineral_reservation"
    OIL_GAS_LEASE = "oil_gas_lease"
    LIFE_ESTATE = "life_estate"
    LEASE = "lease"
    LIEN = "lien"
    MORTGAGE = "mortgage"
    JUDGMENT = "judgment"
    TAXES_NOT_YET_DUE = "taxes_not_yet_due"
    DELINQUENT_TAXES = "delinquent_taxes"
    SURVEY_EXCEPTION = "survey_exception"
    RIPARIAN = "riparian"
    PARTY_WALL = "party_wall"
    ENCROACHMENT = "encroachment"
    GENERAL = "general"
    OTHER = "other"


# ── Classifier ──────────────────────────────────────────────────────────────


def classify_requirement(text: str) -> RequirementType:
    t = text.lower()
    rules = (
        ("mortgage_payoff", ("payoff", "release of mortgage", "satisfy mortgage", "pay off")),
        ("deed_delivery", ("deed of conveyance", "warranty deed", "deliver deed")),
        ("judgment_release", ("judgment", "release of judgment")),
        ("lien_release", ("release of lien", "lien must be", "lien shall be")),
        ("survey_required", ("survey",)),
        ("affidavit", ("affidavit",)),
        ("probate", ("probate", "letters testamentary", "letters of administration")),
        ("tax_payment", ("ad valorem", "current taxes", "delinquent tax")),
        ("hoa_letter", ("homeowner association", "h.o.a", "hoa")),
        ("entity_authority", ("certificate of authority", "good standing", "operating agreement", "borrowing resolution")),
        ("power_of_attorney", ("power of attorney",)),
        ("correction_deed", ("correction deed", "scrivener", "correctly recite")),
        ("encroachment", ("encroach",)),
    )
    for kind, needles in rules:
        for n in needles:
            if n in t:
                return RequirementType(kind)
    return RequirementType.OTHER


def classify_exception(text: str) -> ExceptionType:
    t = text.lower()
    rules = (
        ("utility_easement", ("utility easement",)),
        ("access_easement", ("access easement", "ingress", "egress")),
        ("drainage_easement", ("drainage easement",)),
        ("conservation_easement", ("conservation easement",)),
        ("easement", ("easement",)),
        ("hoa", ("homeowners association", "h.o.a", " hoa ")),
        ("ccr", ("covenants", "restrictions", "ccr", "c.c.r")),
        ("oil_gas_lease", ("oil and gas lease", "oil, gas")),
        ("mineral_reservation", ("mineral", "reserved by")),
        ("life_estate", ("life estate",)),
        ("lease", ("lease",)),
        ("mortgage", ("deed of trust", "mortgage")),
        ("judgment", ("judgment",)),
        ("delinquent_taxes", ("delinquent",)),
        ("taxes_not_yet_due", ("not yet due", "ad valorem taxes for")),
        ("lien", ("lien",)),
        ("survey_exception", ("survey",)),
        ("riparian", ("riparian", "littoral")),
        ("party_wall", ("party wall",)),
        ("encroachment", ("encroach",)),
        ("general", ("rights of parties in possession", "matters of survey", "matters arising")),
    )
    for kind, needles in rules:
        for n in needles:
            if n in t:
                return ExceptionType(kind)
    return ExceptionType.OTHER


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ScheduleA:
    effective_date: dt.date | None
    insured: str | None
    estate: EstateType
    vested_in: str | None
    legal_description: str | None
    policy_amount: float | None
    raw_text: str | None = None


@dataclass(frozen=True, slots=True)
class RequirementItem:
    number: str | None         # "1.", "(a)", etc.
    text: str
    kind: RequirementType


@dataclass(frozen=True, slots=True)
class ExceptionItem:
    number: str | None
    text: str
    kind: ExceptionType
    recording_reference: str | None = None


@dataclass(frozen=True, slots=True)
class TitleCommitment:
    schedule_a: ScheduleA
    requirements: tuple[RequirementItem, ...]
    exceptions: tuple[ExceptionItem, ...]
    raw_text: str = ""
    issued_by: str | None = None


# ── Parsing ─────────────────────────────────────────────────────────────────


_SCHEDULE_A_RE = re.compile(r"SCHEDULE\s+A", re.IGNORECASE)
_SCHEDULE_B1_RE = re.compile(r"SCHEDULE\s+B(?:[\s-]*(?:I|1|Part\s*I))?[^\w]*REQUIREMENTS", re.IGNORECASE)
_SCHEDULE_B2_RE = re.compile(r"SCHEDULE\s+B(?:[\s-]*(?:II|2|Part\s*II))?[^\w]*EXCEPTIONS", re.IGNORECASE)

_EFFECTIVE_DATE_RE = re.compile(r"effective\s+date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_INSURED_RE = re.compile(r"(?:proposed\s+)?insured\s*:?\s*([^\n]+)", re.IGNORECASE)
_VESTED_RE = re.compile(r"(?:title\s+is\s+vested\s+in|estate\s+is\s+vested\s+in)\s*:?\s*([^\n]+)", re.IGNORECASE)
_LEGAL_RE = re.compile(r"(?:legal\s+description|land\s+referred\s+to)\s*:?\s*(.+?)(?:SCHEDULE|END\s+OF\s+SCHEDULE|\Z)", re.IGNORECASE | re.DOTALL)


_NUMBERED_ITEM_RE = re.compile(
    r"""
    ^[\s]*
    (?P<num>(?:\d{1,3}\.|\([a-zA-Z0-9]\)|[a-zA-Z]\.))      # 1.   (a)   a.
    \s*
    (?P<body>.+?)
    (?=^[\s]*(?:\d{1,3}\.|\([a-zA-Z0-9]\)|[a-zA-Z]\.)|\Z)  # next item or end
    """,
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
)


def parse_title_commitment(text: str) -> TitleCommitment:
    """Parse a title-commitment text into structured form."""
    text_norm = re.sub(r"\r\n", "\n", text)

    # Locate section boundaries.
    a_match = _SCHEDULE_A_RE.search(text_norm)
    b1_match = _SCHEDULE_B1_RE.search(text_norm)
    b2_match = _SCHEDULE_B2_RE.search(text_norm)

    a_text = ""
    b1_text = ""
    b2_text = ""
    if a_match:
        end = b1_match.start() if b1_match else (b2_match.start() if b2_match else len(text_norm))
        a_text = text_norm[a_match.end():end]
    if b1_match:
        end = b2_match.start() if b2_match else len(text_norm)
        b1_text = text_norm[b1_match.end():end]
    if b2_match:
        b2_text = text_norm[b2_match.end():]

    schedule_a = _parse_schedule_a(a_text or text_norm)
    requirements = _parse_items(b1_text, classify_requirement, RequirementType, RequirementItem)
    exceptions_raw = _parse_items(b2_text, classify_exception, ExceptionType, ExceptionItem)
    exceptions = tuple(_attach_recording_ref(e) for e in exceptions_raw)

    return TitleCommitment(
        schedule_a=schedule_a,
        requirements=requirements,
        exceptions=exceptions,
        raw_text=text,
    )


def _parse_schedule_a(block: str) -> ScheduleA:
    eff = _EFFECTIVE_DATE_RE.search(block)
    eff_date: dt.date | None = None
    if eff:
        eff_date = _parse_date(eff.group(1))
    amount: float | None = None
    am = _AMOUNT_RE.search(block)
    if am:
        try:
            amount = float(am.group(1).replace(",", ""))
        except ValueError:
            amount = None
    insured = _first_match(_INSURED_RE, block)
    vested = _first_match(_VESTED_RE, block)
    legal = _first_match(_LEGAL_RE, block)

    estate = EstateType.UNKNOWN
    blk_lower = block.lower()
    if "fee simple" in blk_lower:
        estate = EstateType.FEE_SIMPLE
    elif "leasehold" in blk_lower:
        estate = EstateType.LEASEHOLD
    elif "easement" in blk_lower:
        estate = EstateType.EASEMENT
    elif "life estate" in blk_lower:
        estate = EstateType.LIFE_ESTATE

    return ScheduleA(
        effective_date=eff_date,
        insured=insured,
        estate=estate,
        vested_in=vested,
        legal_description=legal,
        policy_amount=amount,
        raw_text=block.strip() or None,
    )


def _parse_items(block: str, classify, kind_enum, item_cls):
    items = []
    for m in _NUMBERED_ITEM_RE.finditer(block):
        body = re.sub(r"\s+", " ", m.group("body")).strip()
        if not body or len(body) < 6:
            continue
        kind = classify(body)
        items.append(item_cls(number=m.group("num"), text=body, kind=kind))
    return tuple(items)


_RECORDING_RE = re.compile(
    r"(?:recorded\s+(?:in|on)|recording\s+(?:no\.|number)|inst\.\s*no\.|instrument\s+no\.)"
    r"\s*([A-Z0-9.\-/ ,]+?)(?:\.|;|,|$)",
    re.IGNORECASE,
)


def _attach_recording_ref(exc: ExceptionItem) -> ExceptionItem:
    m = _RECORDING_RE.search(exc.text)
    if not m:
        return exc
    return ExceptionItem(number=exc.number, text=exc.text, kind=exc.kind, recording_reference=m.group(1).strip())


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    if not m:
        return None
    out = m.group(1).strip()
    # Truncate at next blank line / next ALL CAPS heading.
    out = re.split(r"\n\s*\n|\n\s*[A-Z]{4,}", out, maxsplit=1)[0].strip()
    return out or None


def _parse_date(text: str) -> dt.date | None:
    text = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# ── Risk score / report ────────────────────────────────────────────────────


_HIGH_RISK_REQUIREMENTS = {
    RequirementType.LIEN_RELEASE,
    RequirementType.JUDGMENT_RELEASE,
    RequirementType.PROBATE,
    RequirementType.CORRECTION_DEED,
    RequirementType.ENCROACHMENT,
}

_HIGH_RISK_EXCEPTIONS = {
    ExceptionType.LIEN,
    ExceptionType.JUDGMENT,
    ExceptionType.MORTGAGE,
    ExceptionType.DELINQUENT_TAXES,
    ExceptionType.ENCROACHMENT,
    ExceptionType.MINERAL_RESERVATION,
    ExceptionType.OIL_GAS_LEASE,
}


def risk_score(commitment: TitleCommitment) -> int:
    """Crude 0-100 risk score for triage. Higher = more risk."""
    score = 0
    for r in commitment.requirements:
        score += 10 if r.kind in _HIGH_RISK_REQUIREMENTS else 2
    for e in commitment.exceptions:
        score += 10 if e.kind in _HIGH_RISK_EXCEPTIONS else 1
    return min(100, score)


def write_commitment_report_html(commitment: TitleCommitment, output_path) -> int:
    """Render a self-contained HTML report."""
    sa = commitment.schedule_a
    score = risk_score(commitment)
    color = "#0a8a3a" if score < 25 else "#d39400" if score < 60 else "#c33"

    def _row(item, severity_set):
        sev = item.kind in severity_set
        sev_color = "#c33" if sev else "#5a6a82"
        return (
            f"<tr><td style='color:#5a6a82'>{item.number or ''}</td>"
            f"<td>{item.text}</td>"
            f"<td style='color:{sev_color};font-weight:600'>{item.kind.value}</td></tr>"
        )

    req_rows = "".join(_row(r, _HIGH_RISK_REQUIREMENTS) for r in commitment.requirements)
    exc_rows = "".join(_row(e, _HIGH_RISK_EXCEPTIONS) for e in commitment.exceptions)

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>Title Commitment Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }}
h1 {{ font-size: 18px; color: #1f3b73; margin: 0 0 6px 0; }}
h2 {{ font-size: 14px; color: #1f3b73; margin: 18px 0 6px 0; border-bottom: 1px solid #d3dae8; padding-bottom: 4px; }}
.score {{ display: inline-block; padding: 4px 10px; border-radius: 4px; color: white; font-weight: 600; }}
.kv {{ display: grid; grid-template-columns: 160px 1fr; gap: 4px 14px; font-size: 12px; }}
.kv .lbl {{ color: #5a6a82; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #d3dae8; padding: 6px 10px; text-align: left; }}
th {{ background: #1f3b73; color: white; font-weight: 600; }}
tr:nth-child(even) td {{ background: #f7f9fd; }}
</style></head><body>
<h1>Title Commitment Report</h1>
<div>Risk score: <span class="score" style="background:{color}">{score}/100</span></div>
<h2>Schedule A</h2>
<div class="kv">
  <span class="lbl">Effective Date</span><span>{sa.effective_date or '—'}</span>
  <span class="lbl">Insured</span><span>{sa.insured or '—'}</span>
  <span class="lbl">Estate</span><span>{sa.estate.value}</span>
  <span class="lbl">Vested In</span><span>{sa.vested_in or '—'}</span>
  <span class="lbl">Policy Amount</span><span>{(f"${sa.policy_amount:,.2f}" if sa.policy_amount is not None else "—")}</span>
  <span class="lbl">Legal Description</span><span>{(sa.legal_description or '—')[:600]}</span>
</div>
<h2>Schedule B-I — Requirements ({len(commitment.requirements)})</h2>
<table><thead><tr><th>#</th><th>Requirement</th><th>Type</th></tr></thead><tbody>{req_rows or '<tr><td colspan="3"><em>None.</em></td></tr>'}</tbody></table>
<h2>Schedule B-II — Exceptions ({len(commitment.exceptions)})</h2>
<table><thead><tr><th>#</th><th>Exception</th><th>Type</th></tr></thead><tbody>{exc_rows or '<tr><td colspan="3"><em>None.</em></td></tr>'}</tbody></table>
</body></html>"""
    if hasattr(output_path, "write_text"):
        output_path.write_text(html, encoding="utf-8")
        return output_path.stat().st_size
    return 0
