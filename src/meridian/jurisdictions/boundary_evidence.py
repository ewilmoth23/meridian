"""Boundary determination from heterogeneous evidence.

This is the core intellectual skill of boundary surveying: take many
pieces of evidence — a deed call, a found monument, a possession line, a
neighbor's deed, an aerial photo trace — and decide where the legal
boundary actually sits. Different states have different legal hierarchies.

Texas, for example, follows the classical "calls" hierarchy:

1. Natural monuments (rivers, mountains)
2. Artificial monuments (iron pins, stones marked X)
3. Course (bearing)
4. Distance
5. Quantity (acreage)

California weights *original* monuments (set when the parcel was first
created) above all subsequent measurements; New York adds a strong
preference for occupation evidence after a long uninterrupted period
(Real Property Actions and Proceedings Law § 543).

This module:

* Models pieces of :class:`BoundaryEvidence` with kind, location, and
  confidence.
* Resolves them against state-specific :class:`PriorityRule` lists.
* Computes a weighted-average best-estimate location with covariance.
* Reports per-evidence rejection / agreement statistics.

The :func:`determine_boundary` entry point is deterministic and
defensible — every weight applied is recorded so a reviewer can trace
why a particular point landed where it did.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class EvidenceKind(str, Enum):
    """Categories the surveyor uses to reason about boundary."""

    NATURAL_MONUMENT = "natural_monument"
    ARTIFICIAL_MONUMENT_FOUND = "artificial_monument_found"
    ARTIFICIAL_MONUMENT_RECORD = "artificial_monument_record"
    DEED_CALL_BEARING = "deed_call_bearing"
    DEED_CALL_DISTANCE = "deed_call_distance"
    DEED_CALL_QUANTITY = "deed_call_quantity"
    PLAT_LINE = "plat_line"
    POSSESSION_LINE = "possession_line"
    OCCUPATION_LINE = "occupation_line"
    AGREEMENT_LINE = "agreement_line"
    TAX_MAP_LINE = "tax_map_line"
    AERIAL_PHOTO = "aerial_photo"
    GNSS_OBSERVATION = "gnss_observation"
    ADJOINER_DEED = "adjoiner_deed"
    COURT_ORDER = "court_order"


@dataclass(frozen=True, slots=True)
class BoundaryEvidence:
    """One observed piece of evidence about a single corner."""

    id: str
    kind: EvidenceKind
    x: float
    y: float
    sigma_m: float = 0.05               # 1-σ position uncertainty
    observed_at: dt.date | None = None
    described: str | None = None
    found_by: str | None = None
    notes: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PriorityRule:
    """A single weighting rule from a state's hierarchy."""

    kind: EvidenceKind
    weight: float                       # multiplicative on 1/σ²
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class StateRules:
    """A state's legal weighting + special instructions."""

    state: str
    rules: tuple[PriorityRule, ...]
    citation: str | None = None

    def weight_for(self, kind: EvidenceKind) -> float:
        for r in self.rules:
            if r.kind is kind:
                return r.weight
        return 1.0


# ── Built-in state rule sets ────────────────────────────────────────────────


def _default_priority(state: str, citation: str | None) -> StateRules:
    return StateRules(
        state=state,
        citation=citation,
        rules=(
            PriorityRule(EvidenceKind.NATURAL_MONUMENT, 100.0, "Highest dignity (calls hierarchy)"),
            PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 80.0, "Original artificial monument"),
            PriorityRule(EvidenceKind.COURT_ORDER, 75.0, "Adjudicated boundary"),
            PriorityRule(EvidenceKind.AGREEMENT_LINE, 60.0, "Settled by parties' agreement"),
            PriorityRule(EvidenceKind.PLAT_LINE, 50.0, "Recorded plat depiction"),
            PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_RECORD, 40.0, "Record monument (not found)"),
            PriorityRule(EvidenceKind.DEED_CALL_BEARING, 25.0, "Course (bearing) call"),
            PriorityRule(EvidenceKind.DEED_CALL_DISTANCE, 20.0, "Distance call"),
            PriorityRule(EvidenceKind.OCCUPATION_LINE, 18.0, "Long-standing occupation"),
            PriorityRule(EvidenceKind.POSSESSION_LINE, 15.0, "Possession (not yet ripened)"),
            PriorityRule(EvidenceKind.GNSS_OBSERVATION, 12.0, "GNSS field observation"),
            PriorityRule(EvidenceKind.ADJOINER_DEED, 10.0, "Neighboring parcel's deed"),
            PriorityRule(EvidenceKind.TAX_MAP_LINE, 5.0, "County tax-map line (low dignity)"),
            PriorityRule(EvidenceKind.AERIAL_PHOTO, 4.0, "Aerial photo trace"),
            PriorityRule(EvidenceKind.DEED_CALL_QUANTITY, 2.0, "Acreage call (lowest dignity)"),
        ),
    )


# Eight states with documented priority rules.
TEXAS = _default_priority(
    "TX", "Stafford v. King, 30 Tex. 257 (1867); Texas calls hierarchy"
)

CALIFORNIA = StateRules(
    state="CA",
    citation="Cal. Civil Code §§ 2077; California Land Surveyors Manual",
    rules=(
        PriorityRule(EvidenceKind.NATURAL_MONUMENT, 100.0),
        PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 95.0, "California treats found original monuments as paramount"),
        PriorityRule(EvidenceKind.COURT_ORDER, 80.0),
        PriorityRule(EvidenceKind.AGREEMENT_LINE, 60.0),
        PriorityRule(EvidenceKind.PLAT_LINE, 55.0),
        PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_RECORD, 35.0),
        PriorityRule(EvidenceKind.DEED_CALL_BEARING, 22.0),
        PriorityRule(EvidenceKind.DEED_CALL_DISTANCE, 20.0),
        PriorityRule(EvidenceKind.OCCUPATION_LINE, 15.0),
        PriorityRule(EvidenceKind.POSSESSION_LINE, 12.0),
        PriorityRule(EvidenceKind.GNSS_OBSERVATION, 12.0),
        PriorityRule(EvidenceKind.ADJOINER_DEED, 10.0),
        PriorityRule(EvidenceKind.TAX_MAP_LINE, 4.0),
        PriorityRule(EvidenceKind.AERIAL_PHOTO, 3.0),
        PriorityRule(EvidenceKind.DEED_CALL_QUANTITY, 2.0),
    ),
)

NEW_YORK = StateRules(
    state="NY",
    citation="N.Y. Real Property Actions and Proceedings Law § 543; Brand v. Prince",
    rules=(
        PriorityRule(EvidenceKind.NATURAL_MONUMENT, 100.0),
        PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 80.0),
        PriorityRule(EvidenceKind.COURT_ORDER, 80.0),
        PriorityRule(EvidenceKind.OCCUPATION_LINE, 65.0, "NY heavily weights long-standing occupation (RPAPL §543)"),
        PriorityRule(EvidenceKind.AGREEMENT_LINE, 60.0),
        PriorityRule(EvidenceKind.PLAT_LINE, 50.0),
        PriorityRule(EvidenceKind.ARTIFICIAL_MONUMENT_RECORD, 40.0),
        PriorityRule(EvidenceKind.DEED_CALL_BEARING, 25.0),
        PriorityRule(EvidenceKind.DEED_CALL_DISTANCE, 20.0),
        PriorityRule(EvidenceKind.POSSESSION_LINE, 18.0),
        PriorityRule(EvidenceKind.GNSS_OBSERVATION, 12.0),
        PriorityRule(EvidenceKind.ADJOINER_DEED, 10.0),
        PriorityRule(EvidenceKind.TAX_MAP_LINE, 5.0),
        PriorityRule(EvidenceKind.AERIAL_PHOTO, 4.0),
        PriorityRule(EvidenceKind.DEED_CALL_QUANTITY, 2.0),
    ),
)

FLORIDA = _default_priority("FL", "Fla. Stat. § 472; Spaeth v. Plymouth")
GEORGIA = _default_priority("GA", "O.C.G.A. § 44-4-5")
OHIO = _default_priority("OH", "Ohio Rev. Code §§ 4733; Wilkins v. Wilkins")
COLORADO = _default_priority("CO", "C.R.S. § 38-44-101")
VIRGINIA = _default_priority("VA", "Va. Code Ann. § 54.1-405")


STATE_RULES: dict[str, StateRules] = {
    s.state: s for s in (TEXAS, CALIFORNIA, NEW_YORK, FLORIDA, GEORGIA, OHIO, COLORADO, VIRGINIA)
}


def get_state_rules(state: str) -> StateRules:
    """Return the StateRules for ``state``; defaults to Texas-style hierarchy."""
    return STATE_RULES.get(state.upper(), _default_priority(state.upper(), None))


# ── Determination ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WeightedContribution:
    """How much weight each evidence piece carried in the final answer."""

    evidence_id: str
    kind: EvidenceKind
    weight: float
    residual_m: float


@dataclass(frozen=True, slots=True)
class Determination:
    """Output of :func:`determine_boundary` for one corner."""

    x: float
    y: float
    sigma_x: float
    sigma_y: float
    state: str
    citation: str | None
    contributions: tuple[WeightedContribution, ...]
    rejected: tuple[str, ...]
    n_evidence: int


def determine_boundary(
    evidence: list[BoundaryEvidence],
    *,
    state: str = "TX",
    blunder_sigmas: float = 3.0,
) -> Determination:
    """Compute the best estimate location of a corner from heterogeneous evidence.

    Algorithm:

    1. Look up the state's :class:`StateRules` and assign each evidence
       piece a base weight = ``rule.weight × 1/σ²``.
    2. Compute the initial weighted mean position.
    3. Reject blunders: any piece more than ``blunder_sigmas`` × σ away
       from the mean is dropped.
    4. Recompute the weighted mean from the survivors.
    5. Return :class:`Determination` with full contribution accounting.
    """
    if not evidence:
        raise ValueError("Need at least one piece of evidence.")
    rules = get_state_rules(state)
    xs = np.fromiter((e.x for e in evidence), dtype=np.float64, count=len(evidence))
    ys = np.fromiter((e.y for e in evidence), dtype=np.float64, count=len(evidence))
    sigmas = np.fromiter(
        (max(e.sigma_m, 1e-6) for e in evidence), dtype=np.float64, count=len(evidence)
    )
    base_w = np.fromiter(
        (rules.weight_for(e.kind) for e in evidence), dtype=np.float64, count=len(evidence)
    )
    # Combined precision-weighted weights.
    weights = base_w / (sigmas * sigmas)

    # Initial mean.
    initial_x = float(np.average(xs, weights=weights))
    initial_y = float(np.average(ys, weights=weights))

    # Spread for blunder detection.
    dx = xs - initial_x
    dy = ys - initial_y
    residual = np.sqrt(dx * dx + dy * dy)
    rms = float(np.sqrt(np.average(residual * residual, weights=weights))) or 1e-6

    keep_mask = residual <= max(blunder_sigmas * rms, blunder_sigmas * sigmas.max())
    rejected_ids = tuple(e.id for e, keep in zip(evidence, keep_mask) if not keep)

    if not keep_mask.any():
        # Fall back to all if rejection would empty everything.
        keep_mask = np.ones_like(keep_mask, dtype=bool)
        rejected_ids = ()

    final_w = weights[keep_mask]
    final_x = float(np.average(xs[keep_mask], weights=final_w))
    final_y = float(np.average(ys[keep_mask], weights=final_w))

    sum_w = float(final_w.sum())
    sigma_x = float(np.sqrt(((xs[keep_mask] - final_x) ** 2 * final_w).sum() / max(sum_w, 1e-12)))
    sigma_y = float(np.sqrt(((ys[keep_mask] - final_y) ** 2 * final_w).sum() / max(sum_w, 1e-12)))

    contributions = tuple(
        WeightedContribution(
            evidence_id=e.id,
            kind=e.kind,
            weight=float(weights[i]),
            residual_m=float(residual[i]),
        )
        for i, e in enumerate(evidence)
        if keep_mask[i]
    )

    return Determination(
        x=final_x,
        y=final_y,
        sigma_x=sigma_x,
        sigma_y=sigma_y,
        state=rules.state,
        citation=rules.citation,
        contributions=contributions,
        rejected=rejected_ids,
        n_evidence=len(evidence),
    )


# ── Report ──────────────────────────────────────────────────────────────────


def write_evidence_report_html(
    evidence: list[BoundaryEvidence],
    determination: Determination,
    output_path,
) -> int:
    """Render a self-contained HTML evidence report."""
    rows = []
    contributors = {c.evidence_id: c for c in determination.contributions}
    for e in evidence:
        contrib = contributors.get(e.id)
        rejected = e.id in determination.rejected
        weight = f"{contrib.weight:.2f}" if contrib else "—"
        residual = f"{contrib.residual_m:.4f} m" if contrib else "—"
        verdict = "rejected" if rejected else "used"
        color = "#c33" if rejected else "#0a8a3a"
        rows.append(
            f"<tr><td>{e.id}</td><td>{e.kind.value}</td>"
            f"<td>({e.x:.4f}, {e.y:.4f})</td><td>{e.sigma_m:.4f} m</td>"
            f"<td>{weight}</td><td>{residual}</td>"
            f"<td style='color:{color};font-weight:600'>{verdict}</td></tr>"
        )
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />
<title>Boundary Evidence Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: #1a2540; padding: 24px; }}
h1 {{ font-size: 20px; color: #1f3b73; margin: 0 0 4px 0; }}
.subtitle {{ color: #5a6a82; font-size: 12px; margin-bottom: 16px; }}
.card {{ background: #f7f9fd; border-left: 4px solid #1f3b73; padding: 12px 18px; margin: 12px 0; }}
.card .lbl {{ color: #5a6a82; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
.card .val {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }}
th, td {{ border: 1px solid #d3dae8; padding: 6px 10px; text-align: left; }}
th {{ background: #1f3b73; color: white; font-weight: 600; }}
tr:nth-child(even) td {{ background: #f7f9fd; }}
.cit {{ font-size: 10px; color: #5a6a82; font-style: italic; }}
</style></head><body>
<h1>Boundary Evidence Determination</h1>
<div class="subtitle">State: {determination.state} · {determination.n_evidence} pieces of evidence considered</div>
<div class="card">
  <div><span class="lbl">Best-estimate corner</span></div>
  <div class="val">x = {determination.x:.4f},  y = {determination.y:.4f}</div>
  <div class="val">σx = ±{determination.sigma_x:.4f} m,  σy = ±{determination.sigma_y:.4f} m</div>
  <div class="cit">{determination.citation or ''}</div>
</div>
<table>
<thead><tr><th>ID</th><th>Kind</th><th>Position</th><th>σ</th><th>Weight</th><th>Residual</th><th>Verdict</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>"""
    if hasattr(output_path, "write_text"):
        output_path.write_text(body, encoding="utf-8")
        return output_path.stat().st_size
    return 0
