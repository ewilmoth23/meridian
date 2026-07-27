"""Curve-table generator tests."""

from __future__ import annotations

import csv
import math

import pytest

from meridian.adapters.reports.curve_table import (
    CurveData,
    write_curve_table_csv,
    write_curve_table_html,
    write_curve_table_text,
)


def _square_curves() -> list[CurveData]:
    return [
        CurveData.from_inputs(
            label="C1",
            radius=100.0,
            delta=math.radians(90.0),
            chord_bearing=math.radians(45.0),
            clockwise=True,
        ),
        CurveData.from_inputs(
            label="C2",
            radius=50.0,
            delta=math.radians(60.0),
            chord_bearing=math.radians(135.0),
            clockwise=False,
        ),
    ]


def test_curve_geometry_for_known_inputs():
    c = CurveData.from_inputs(
        label="C1",
        radius=100.0,
        delta=math.radians(90.0),
        chord_bearing=math.radians(45.0),
        clockwise=True,
    )
    # L = R * Δ
    assert c.arc_length_m == pytest.approx(100.0 * math.pi / 2)
    # C = 2R sin(Δ/2) = 2*100*sin(45°) = 141.421...
    assert c.chord_length_m == pytest.approx(141.42135623, abs=1e-6)
    # T = R tan(Δ/2) = 100
    assert c.tangent_length_m == pytest.approx(100.0)


def test_curve_data_rejects_bad_inputs():
    with pytest.raises(ValueError):
        CurveData.from_inputs(label="X", radius=0.0, delta=1.0, chord_bearing=0, clockwise=True)
    with pytest.raises(ValueError):
        CurveData.from_inputs(label="X", radius=10.0, delta=0.0, chord_bearing=0, clockwise=True)


def test_csv_round_trips_columns(tmp_path):
    out = tmp_path / "curves.csv"
    write_curve_table_csv(_square_curves(), out)
    rows = list(csv.reader(out.read_text().splitlines()))
    assert rows[0][0] == "Label"
    assert rows[1][0] == "C1"
    assert rows[2][0] == "C2"
    assert "CW" in rows[1] and "CCW" in rows[2]


def test_html_contains_table(tmp_path):
    out = tmp_path / "curves.html"
    write_curve_table_html(_square_curves(), out)
    text = out.read_text()
    assert "<table>" in text
    assert "C1" in text and "C2" in text


def test_text_table_has_aligned_columns():
    text = write_curve_table_text(_square_curves())
    lines = text.splitlines()
    assert lines[0].startswith("#")
    # Separator line of dashes should match width.
    assert "----" in lines[1]
