"""PLSS parser + boundary computer tests."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS
from meridian.jurisdictions.plss import (
    AliquotPart,
    Direction,
    aliquot_box,
    is_plss_description,
    parse_plss,
    plss_polygon,
    section_area_acres,
    section_corners,
)

# ── Parsing ────────────────────────────────────────────────────────────────


def test_basic_parse():
    text = "The Northwest 1/4 of Section 14, Township 2 North, Range 3 East, of the 6th Principal Meridian"
    desc = parse_plss(text)
    assert desc.section == 14
    assert desc.township_range.township == 2
    assert desc.township_range.township_dir is Direction.NORTH
    assert desc.township_range.range == 3
    assert desc.township_range.range_dir is Direction.EAST
    assert desc.aliquot is not None
    assert desc.aliquot.parts == ("NW",)
    assert desc.township_range.meridian == "6th"


def test_nested_aliquot_parse():
    text = "NE 1/4 of the SW 1/4 of Section 7, T1S R2W, Mount Diablo Meridian"
    desc = parse_plss(text)
    assert desc.section == 7
    assert desc.aliquot is not None
    assert desc.aliquot.parts == ("NE", "SW")
    assert desc.township_range.meridian == "Mount Diablo"


def test_compact_form_works():
    desc = parse_plss("Section 1, T2N R3E, 6th P.M.")
    assert desc.section == 1
    assert desc.aliquot is None


def test_is_plss_description_detector():
    assert is_plss_description("Section 14, T2N R3E")
    assert not is_plss_description("Beginning at a stake; thence N 45°00'00\" E 100 feet …")


def test_parse_rejects_non_plss():
    with pytest.raises(ValueError, match="Not a PLSS"):
        parse_plss("Beginning at the POB; thence N 90°00'00\" E 100 meters")


# ── Section corners (serpentine) ───────────────────────────────────────────


def test_section_1_is_ne_corner():
    sw_x, sw_y, w, h = section_corners(1)
    # Section 1 occupies the NE-most cell. SW corner is at (5*MILE, 5*MILE) of the township.
    assert sw_x == pytest.approx(5 * 1609.344, abs=1e-3)
    assert sw_y == pytest.approx(5 * 1609.344, abs=1e-3)
    assert w == pytest.approx(1609.344)
    assert h == pytest.approx(1609.344)


def test_section_6_is_nw_corner():
    sw_x, sw_y, _, _ = section_corners(6)
    assert sw_x == pytest.approx(0.0, abs=1e-6)
    assert sw_y == pytest.approx(5 * 1609.344, abs=1e-3)


def test_section_36_is_se_corner():
    sw_x, sw_y, _, _ = section_corners(36)
    assert sw_x == pytest.approx(5 * 1609.344, abs=1e-3)
    assert sw_y == pytest.approx(0.0, abs=1e-6)


def test_section_31_is_sw_corner():
    sw_x, sw_y, _, _ = section_corners(31)
    assert sw_x == pytest.approx(0.0, abs=1e-6)
    assert sw_y == pytest.approx(0.0, abs=1e-6)


def test_section_invalid_raises():
    with pytest.raises(ValueError):
        section_corners(0)
    with pytest.raises(ValueError):
        section_corners(37)


# ── Aliquot ────────────────────────────────────────────────────────────────


def test_aliquot_box_quarters_recursively():
    # Section 14 NW quarter — should sit in the upper-left corner of section 14.
    sw_x, sw_y, w, h = section_corners(14)
    # NW¼ of section 14: SW corner is shifted up by half a section.
    nx, ny, nw, nh = aliquot_box(14, AliquotPart(parts=("NW",)))
    assert nx == pytest.approx(sw_x, abs=1e-6)
    assert ny == pytest.approx(sw_y + h / 2, abs=1e-3)
    assert nw == pytest.approx(w / 2, abs=1e-3)
    assert nh == pytest.approx(h / 2, abs=1e-3)


def test_aliquot_acres_for_quarter_quarter():
    assert section_area_acres(None) == 640.0
    assert section_area_acres(AliquotPart(parts=("NW",))) == 160.0
    assert section_area_acres(AliquotPart(parts=("NW", "SE"))) == 40.0


# ── Polygon ────────────────────────────────────────────────────────────────


def test_plss_polygon_area_matches_aliquot():
    crs = CRS(epsg=2277)
    desc = parse_plss("NW 1/4 of Section 14, T2N R3E, 6th P.M.")
    poly = plss_polygon(desc, crs)
    # 160 acres = 160 * 4046.8564224 m² = ~647 497 m²
    assert poly.area() == pytest.approx(160 * 4046.8564224, rel=1e-4)
