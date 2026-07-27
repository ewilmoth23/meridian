"""Chain-of-title tests — gap / fork / wild-deed / inversion detection."""

from __future__ import annotations

import datetime as dt

from meridian.domain.deed import (
    Deed,
    DeedKind,
    Party,
    PartyRole,
    Recording,
)
from meridian.jurisdictions.chain_of_title import (
    DefectKind,
    build_chain,
    normalize_name,
    write_chain_html,
)


def _deed(deed_id, grantor, grantee, year, instrument):
    return Deed(
        id=deed_id,
        kind=DeedKind.WARRANTY,
        parties=(
            Party(name=grantor, role=PartyRole.GRANTOR),
            Party(name=grantee, role=PartyRole.GRANTEE),
        ),
        recording=Recording(
            jurisdiction="Springfield County",
            instrument_number=instrument,
            recorded_date=dt.date(year, 1, 15),
        ),
    )


def test_clean_chain_has_no_defects():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        _deed("d2", "Alice", "Bob", 1925, "INST-002"),
        _deed("d3", "Bob", "Carol", 1950, "INST-003"),
        _deed("d4", "Carol", "Dave", 1975, "INST-004"),
    ]
    chain = build_chain("parcel-1", deeds)
    assert len(chain.links) == 4
    assert chain.defects == ()


def test_wild_deed_detected():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        # Eve never received title; this is a wild deed.
        _deed("d-wild", "Eve", "Bob", 1925, "INST-WILD"),
    ]
    chain = build_chain("parcel-1", deeds)
    kinds = {d.kind for d in chain.defects}
    assert DefectKind.WILD_DEED in kinds


def test_self_conveyance_flagged():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        _deed("d2", "Alice", "Alice", 1925, "INST-002"),
    ]
    chain = build_chain("parcel-1", deeds)
    assert any(d.kind is DefectKind.SELF_CONVEYANCE for d in chain.defects)


def test_fork_detected():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        _deed("d2", "Alice", "Bob", 1925, "INST-002"),
        _deed("d3", "Alice", "Carol", 1930, "INST-003"),  # fork: Alice already conveyed to Bob
    ]
    chain = build_chain("parcel-1", deeds)
    assert any(d.kind is DefectKind.FORK for d in chain.defects)


def test_duplicate_instrument_flagged():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        _deed("d2", "Alice", "Bob", 1925, "INST-002"),
        _deed("d3", "Bob", "Carol", 1930, "INST-002"),  # duplicate instrument number
    ]
    chain = build_chain("parcel-1", deeds)
    assert any(d.kind is DefectKind.DUPLICATE for d in chain.defects)


def test_gap_detected_for_long_holes():
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        # 50-year gap to next conveyance
        _deed("d2", "Alice", "Bob", 1955, "INST-002"),
    ]
    chain = build_chain("parcel-1", deeds)
    assert any(d.kind is DefectKind.GAP for d in chain.defects)


def test_normalize_name_strips_suffixes():
    assert normalize_name("John Smith Jr.") == "john smith"
    assert normalize_name("Smith, John, et ux.") == "smith john"


def test_html_writes(tmp_path):
    deeds = [
        _deed("d1", "United States", "Alice", 1900, "INST-001"),
        _deed("d2", "Alice", "Bob", 1925, "INST-002"),
    ]
    chain = build_chain("parcel-1", deeds)
    out = tmp_path / "chain.html"
    write_chain_html(chain, out)
    text = out.read_text()
    assert "Chain of Title" in text
    assert "Alice" in text and "Bob" in text
