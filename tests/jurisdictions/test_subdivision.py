"""Subdivision parser tests."""

from __future__ import annotations

from meridian.jurisdictions.subdivision import (
    FeatureKind,
    parse_subdivision,
    write_subdivision_report_html,
)

SAMPLE = """
A subdivision of 23.45 acres known as Sunset Ridge Estates, recorded in Cabinet
P, Slide 412 of the Travis County Map Records.

Lot 1, Block A: BEGINNING at the northwest corner; thence S 85°15'00" E a
distance of 110.20 feet to a point.

Lot 2, Block A: BEGINNING at the northeast corner of Lot 1; thence S 85°15'00" E
a distance of 95.50 feet.

Lot 3, Block B: described in metes and bounds.

Lot 4, Block B: also described in metes and bounds.

Sunset Ridge Drive is a 60-foot wide right-of-way, dedicated to public use.
Sunset Ridge Court is a 50-foot wide cul-de-sac.

Common Area 1 is reserved as Open Space for use by the homeowners.
Detention Pond is part of the Drainage Easement granted to the County.
"""


def test_parses_subdivision_name_and_recording():
    sub = parse_subdivision(SAMPLE)
    assert "Sunset Ridge" in sub.name
    assert sub.recording_reference is not None and "P" in sub.recording_reference


def test_parses_lots_with_blocks():
    sub = parse_subdivision(SAMPLE)
    nums = {(lot.number, lot.block) for lot in sub.lots}
    assert ("1", "A") in nums
    assert ("2", "A") in nums
    assert ("3", "B") in nums
    assert ("4", "B") in nums


def test_blocks_count_lots_correctly():
    sub = parse_subdivision(SAMPLE)
    counts = {b.name: b.lot_count for b in sub.blocks}
    assert counts["A"] == 2
    assert counts["B"] == 2


def test_streets_with_widths_extracted():
    sub = parse_subdivision(SAMPLE)
    names = {s.name for s in sub.streets}
    assert any(n == "Sunset Ridge Drive" or n.startswith("Sunset Ridge Drive") for n in names)
    drive = next(s for s in sub.streets if s.name.startswith("Sunset Ridge Drive"))
    # 60 ft → ~18.288 m.
    assert drive.width_m is not None and 17 < drive.width_m < 19


def test_common_areas_classified():
    sub = parse_subdivision(SAMPLE)
    kinds = {c.kind for c in sub.common_areas}
    assert FeatureKind.COMMON_AREA in kinds
    assert FeatureKind.DRAINAGE in kinds


def test_subdivision_html_writes(tmp_path):
    sub = parse_subdivision(SAMPLE)
    out = tmp_path / "sub.html"
    write_subdivision_report_html(sub, out)
    assert out.exists()
    text = out.read_text()
    assert "Sunset Ridge" in text
    assert "Lot" in text
