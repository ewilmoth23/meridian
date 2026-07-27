"""Boundary-evidence analyzer tests."""

from __future__ import annotations

import pytest

from meridian.jurisdictions.boundary_evidence import (
    STATE_RULES,
    BoundaryEvidence,
    EvidenceKind,
    determine_boundary,
    get_state_rules,
    write_evidence_report_html,
)


def _ev(eid, kind, x, y, sigma=0.05):
    return BoundaryEvidence(id=eid, kind=kind, x=x, y=y, sigma_m=sigma)


def test_state_rules_lookup():
    assert get_state_rules("TX").state == "TX"
    assert get_state_rules("CA").state == "CA"
    # Unknown state returns a Texas-style default.
    fake = get_state_rules("XX")
    assert fake.state == "XX"
    assert fake.weight_for(EvidenceKind.NATURAL_MONUMENT) >= fake.weight_for(EvidenceKind.DEED_CALL_QUANTITY)


def test_monument_outweighs_distance_call():
    # A found iron pin and a distance call disagree by 2 m. The pin should win.
    pin = _ev("pin", EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 100.0, 200.0, sigma=0.03)
    call = _ev("call", EvidenceKind.DEED_CALL_DISTANCE, 102.0, 200.0, sigma=0.50)
    det = determine_boundary([pin, call], state="TX")
    # Result should be pulled toward the pin (much lower σ + higher base weight).
    assert det.x == pytest.approx(100.0, abs=0.5)
    assert det.y == pytest.approx(200.0, abs=0.5)


def test_blunder_evidence_rejected():
    # A natural monument at (10, 10) plus a wildly bad GNSS reading.
    nat = _ev("nat", EvidenceKind.NATURAL_MONUMENT, 10.0, 10.0, sigma=0.10)
    bad = _ev("bad", EvidenceKind.GNSS_OBSERVATION, 50.0, 60.0, sigma=0.30)
    det = determine_boundary([nat, bad], state="TX", blunder_sigmas=2.0)
    # The blunder is flagged.
    assert "bad" in det.rejected
    assert det.x == pytest.approx(10.0, abs=0.5)
    assert det.y == pytest.approx(10.0, abs=0.5)


def test_ny_weights_occupation_above_other_states():
    occupation = _ev("occ", EvidenceKind.OCCUPATION_LINE, 1.0, 0.0, sigma=0.10)
    distance = _ev("dist", EvidenceKind.DEED_CALL_DISTANCE, 0.0, 0.0, sigma=0.10)
    ny = determine_boundary([occupation, distance], state="NY")
    tx = determine_boundary([occupation, distance], state="TX")
    # NY should weight occupation more heavily, pulling x closer to 1.0.
    assert ny.x > tx.x


def test_zero_evidence_raises():
    with pytest.raises(ValueError, match="at least one"):
        determine_boundary([], state="TX")


def test_html_report_writes(tmp_path):
    evidence = [
        _ev("pin", EvidenceKind.ARTIFICIAL_MONUMENT_FOUND, 0.0, 0.0),
        _ev("call", EvidenceKind.DEED_CALL_DISTANCE, 0.5, 0.0, sigma=0.30),
    ]
    det = determine_boundary(evidence, state="TX")
    out = tmp_path / "evidence.html"
    write_evidence_report_html(evidence, det, out)
    text = out.read_text()
    assert "Boundary Evidence" in text
    assert "TX" in text
    assert "pin" in text


def test_state_rules_register_eight_states():
    expected = {"TX", "CA", "NY", "FL", "GA", "OH", "CO", "VA"}
    assert expected.issubset(set(STATE_RULES))
