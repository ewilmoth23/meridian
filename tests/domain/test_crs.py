"""Tests for CRS construction and helpers."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS, WGS84, LinearUnit, state_plane, utm


def test_wgs84_is_geographic():
    assert WGS84.is_geographic()
    assert WGS84.epsg == 4326


def test_state_plane_reports_us_ft():
    crs = state_plane(2277)
    assert crs.epsg == 2277
    assert crs.units is LinearUnit.US_SURVEY_FOOT
    assert crs.is_projected()


def test_utm_zone_14_north():
    crs = utm(14, "N")
    assert crs.is_projected()
    assert crs.epsg == 26900 + 14


def test_crs_requires_identifier():
    with pytest.raises(ValueError):
        CRS()


def test_linear_unit_to_meter_constant_for_us_ft():
    assert LinearUnit.US_SURVEY_FOOT.to_meter == pytest.approx(0.3048006096)
