"""Closure-analysis report tests."""

from __future__ import annotations

import math

import pytest

from meridian.adapters.reports.closure_report import (
    ClosureStandard,
    analyze,
    write_closure_report_html,
    write_closure_report_text,
)


def test_perfect_square_passes_first_order():
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.0]
    report = analyze(
        bearings=bearings,
        distances=distances,
        standard=ClosureStandard.FIRST_ORDER,
    )
    for m in report.methods:
        assert m.pass_ratio
        assert m.area_m2 == pytest.approx(10000.0, abs=1e-3)
    assert report.area_dmd_m2 == pytest.approx(10000.0, abs=1e-3)


def test_closure_error_propagates_to_failure():
    # Tiny error in last leg breaks 1:100,000 but not 1:1,000.
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.05]
    high = analyze(bearings=bearings, distances=distances, standard=ClosureStandard.FIRST_ORDER)
    low = analyze(bearings=bearings, distances=distances, standard=ClosureStandard.CONSTRUCTION)
    unadjusted_high = next(m for m in high.methods if m.method == "Unadjusted")
    unadjusted_low = next(m for m in low.methods if m.method == "Unadjusted")
    assert unadjusted_high.pass_ratio is False
    assert unadjusted_low.pass_ratio is True
    # Compass + transit reduce closure to ~zero, so they pass at any standard.
    for m in high.methods:
        if m.method != "Unadjusted":
            assert m.pass_ratio


def test_text_report_contains_method_names():
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.0]
    text = write_closure_report_text(analyze(bearings=bearings, distances=distances))
    assert "Compass" in text
    assert "Transit" in text


def test_html_report_writes_file(tmp_path):
    bearings = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    distances = [100.0, 100.0, 100.0, 100.0]
    out = tmp_path / "closure.html"
    write_closure_report_html(analyze(bearings=bearings, distances=distances), out)
    assert out.exists()
    text = out.read_text()
    assert "Closure Analysis" in text
    assert "PASS" in text
