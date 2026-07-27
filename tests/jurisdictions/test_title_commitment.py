"""Title-commitment parser tests."""

from __future__ import annotations

import datetime as dt

from meridian.jurisdictions.title_commitment import (
    EstateType,
    ExceptionType,
    RequirementType,
    classify_exception,
    classify_requirement,
    parse_title_commitment,
    risk_score,
    write_commitment_report_html,
)

SAMPLE = """
SCHEDULE A
Effective Date: March 14, 2026
Proposed Insured: First National Bank of Springfield
The estate or interest in the Land insured by this Commitment is: Fee Simple
Title is vested in: John Smith and Jane Smith, husband and wife
Land referred to: Lot 5, Block 2, Sunset Acres Subdivision, Springfield County

SCHEDULE B-I REQUIREMENTS
1. Pay the agreed amount for the title insurance.
2. Obtain payoff and release of mortgage to ABC Bank recorded in Volume 234, Page 56.
3. Survey of the subject property must be obtained.
4. Affidavit of debts and liens executed by the Sellers.

SCHEDULE B-II EXCEPTIONS
1. Taxes for the year 2026, a lien not yet due and payable.
2. Easement granted to Springfield Power and Light recorded May 1, 1972, Inst. No. 19720501.
3. Restrictive covenants and conditions recorded in Volume 100, Page 200.
4. Mineral reservation in deed from John Smith to Jane Smith recorded April 2, 1995.
5. Rights of parties in possession.
"""


def test_schedule_a_extracts_fields():
    c = parse_title_commitment(SAMPLE)
    assert c.schedule_a.effective_date == dt.date(2026, 3, 14)
    assert c.schedule_a.estate is EstateType.FEE_SIMPLE
    assert "John Smith" in (c.schedule_a.vested_in or "")
    assert "Lot 5" in (c.schedule_a.legal_description or "")


def test_requirements_classified():
    c = parse_title_commitment(SAMPLE)
    kinds = {r.kind for r in c.requirements}
    assert RequirementType.MORTGAGE_PAYOFF in kinds
    assert RequirementType.SURVEY_REQUIRED in kinds
    assert RequirementType.AFFIDAVIT in kinds


def test_exceptions_classified():
    c = parse_title_commitment(SAMPLE)
    kinds = {e.kind for e in c.exceptions}
    assert ExceptionType.TAXES_NOT_YET_DUE in kinds
    assert ExceptionType.UTILITY_EASEMENT in kinds or ExceptionType.EASEMENT in kinds
    assert ExceptionType.CCR in kinds
    assert ExceptionType.MINERAL_RESERVATION in kinds


def test_recording_reference_attached():
    c = parse_title_commitment(SAMPLE)
    refs = [e.recording_reference for e in c.exceptions if e.recording_reference]
    assert any("19720501" in (r or "") for r in refs)


def test_risk_score_in_range():
    c = parse_title_commitment(SAMPLE)
    score = risk_score(c)
    assert 0 <= score <= 100


def test_classify_requirement_unknown_text_returns_other():
    assert classify_requirement("blah") is RequirementType.OTHER


def test_classify_exception_lien_classifies_as_lien():
    assert classify_exception("Mechanic's lien filed by ABC Builders") is ExceptionType.LIEN


def test_html_report_writes(tmp_path):
    out = tmp_path / "commitment.html"
    write_commitment_report_html(parse_title_commitment(SAMPLE), out)
    text = out.read_text()
    assert "Title Commitment Report" in text
    assert "Schedule A" in text
    assert "Schedule B-I" in text
    assert "Schedule B-II" in text
