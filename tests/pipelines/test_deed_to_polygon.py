"""Slice 1 pipeline tests — deed text → boundary."""

from __future__ import annotations

import math

import pytest

from meridian.domain.geometry import Point2D
from meridian.pipelines.deed_to_polygon import (
    DeedParseError,
    boundary_from_calls,
    parse_bearing,
    parse_deed_text,
    parse_distance,
)


def test_parse_bearing_quadrants():
    assert parse_bearing("N 0°00'00\" E") == pytest.approx(0.0, abs=1e-9)
    assert parse_bearing("N 90°00'00\" E") == pytest.approx(math.pi / 2)
    assert parse_bearing("S 0°00'00\" E") == pytest.approx(math.pi)
    assert parse_bearing("N 90°00'00\" W") == pytest.approx(3 * math.pi / 2)


def test_parse_distance_meters_and_feet():
    assert parse_distance("100 meters") == pytest.approx(100.0)
    assert parse_distance("100 feet") == pytest.approx(30.48)
    assert parse_distance("100 chains") == pytest.approx(2011.68)


def test_parse_deed_square_text(square_calls_text):
    parsed = parse_deed_text(square_calls_text)
    assert len(parsed.calls) == 4
    assert parsed.point_of_beginning_text is not None


def test_boundary_from_calls_closes_perfectly(square_calls_text, crs_local):
    parsed = parse_deed_text(square_calls_text)
    pob = Point2D(0.0, 0.0, crs_local)
    boundary = boundary_from_calls(parsed.calls, pob)
    assert boundary.misclosure_distance == pytest.approx(0.0, abs=1e-9)
    assert boundary.perimeter == pytest.approx(400.0, abs=1e-6)
    assert boundary.polygon.area() == pytest.approx(10000.0, abs=1e-3)


def test_empty_text_raises():
    with pytest.raises(DeedParseError):
        parse_deed_text("")


def test_unparseable_returns_no_calls():
    with pytest.raises(DeedParseError):
        parse_deed_text("This is not a deed.")
