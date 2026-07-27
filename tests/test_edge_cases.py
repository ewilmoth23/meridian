"""Edge-case sweep — empty inputs, single-leg traverses, malformed data, etc.

Each test asks: "what happens if the user does the obvious wrong thing?".
The bar is: the module rejects with a clear error message OR returns a
defensible empty/zero result. *Never* silently produce garbage.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

# ── Domain — Polygon ────────────────────────────────────────────────────────


def test_polygon_rejects_two_point_ring(crs_local):
    from meridian.domain.geometry import Point2D, Polygon

    with pytest.raises(ValueError, match="at least 4 points"):
        Polygon(exterior=(Point2D(0, 0, crs_local), Point2D(1, 1, crs_local), Point2D(0, 0, crs_local)))


def test_polygon_rejects_unclosed_ring(crs_local):
    from meridian.domain.geometry import Point2D, Polygon

    with pytest.raises(ValueError, match="not closed"):
        Polygon(
            exterior=(
                Point2D(0, 0, crs_local),
                Point2D(1, 0, crs_local),
                Point2D(1, 1, crs_local),
                Point2D(0, 1, crs_local),  # missing the closing point
            )
        )


def test_polygon_rejects_mixed_crs(crs_local, texas_central_crs):
    from meridian.domain.geometry import Point2D, Polygon

    with pytest.raises(ValueError, match="share a CRS"):
        Polygon(
            exterior=(
                Point2D(0, 0, crs_local),
                Point2D(1, 0, texas_central_crs),
                Point2D(1, 1, crs_local),
                Point2D(0, 1, crs_local),
                Point2D(0, 0, crs_local),
            )
        )


# ── Domain — CRS ────────────────────────────────────────────────────────────


def test_crs_rejects_construction_with_no_identifier():
    from meridian.domain.crs import CRS

    with pytest.raises(ValueError, match="at least one of"):
        CRS()


# ── Math — COGO ────────────────────────────────────────────────────────────


def test_inverse_zero_distance_returns_zero():
    from meridian.math.cogo import inverse

    res = inverse((5.0, 5.0), (5.0, 5.0))
    assert res.distance == 0.0


def test_run_traverse_rejects_mismatched_lengths():
    from meridian.math.cogo import run_traverse

    with pytest.raises(ValueError, match="same length"):
        run_traverse((0, 0), [0.0, 1.0], [10.0])


def test_intersect_parallel_bearings_raises():
    from meridian.math.cogo import intersect_bearing_bearing

    with pytest.raises(ValueError, match="parallel"):
        intersect_bearing_bearing((0, 0), 0.0, (10, 0), 0.0)


def test_intersect_distance_circles_too_far_raises():
    from meridian.math.cogo import intersect_distance_distance

    with pytest.raises(ValueError, match="do not intersect"):
        intersect_distance_distance((0, 0), 1.0, (10, 0), 1.0)


def test_compass_adjust_zero_perimeter_raises():
    from meridian.math.cogo import adjust_compass

    with pytest.raises(ValueError, match="zero perimeter"):
        adjust_compass([0.0, math.pi], [0.0, 0.0], 1.0, 0.0)


# ── Math — Adjustment ─────────────────────────────────────────────────────


def test_adjustment_rejects_underdetermined_system():
    from meridian.math.adjustment import AdjustmentSpec, solve_step

    a = np.array([[1.0, 0.0]])
    l = np.array([5.0])
    w = np.array([1.0])
    with pytest.raises(ValueError, match="under-determined"):
        solve_step(AdjustmentSpec(a=a, l=l, w=w))


def test_adjustment_rejects_shape_mismatch():
    from meridian.math.adjustment import AdjustmentSpec, solve_step

    a = np.zeros((4, 2))
    l = np.zeros(3)
    w = np.zeros(4)
    with pytest.raises(ValueError, match="Shape mismatch"):
        solve_step(AdjustmentSpec(a=a, l=l, w=w))


def test_chi_square_fails_with_zero_redundancy():
    from meridian.math.adjustment import chi_square_test

    assert chi_square_test(1.0, 0) is False


# ── Network adjustment pipeline ────────────────────────────────────────────


def test_network_adjust_rejects_empty_network():
    from meridian.domain.crs import CRS
    from meridian.domain.network import ConstraintMode, ControlNetwork
    from meridian.pipelines.network_adjust import adjust

    crs = CRS(epsg=2277)
    net = ControlNetwork(
        name="empty",
        crs=crs,
        points=(),
        observations=(),
        constraint_mode=ConstraintMode.MINIMAL,
    )
    with pytest.raises(ValueError, match="empty network"):
        adjust(net)


# ── Deed pipeline ─────────────────────────────────────────────────────────


def test_deed_parser_rejects_empty_string():
    from meridian.pipelines.deed_to_polygon import DeedParseError, parse_deed_text

    with pytest.raises(DeedParseError):
        parse_deed_text("")


def test_deed_parser_rejects_garbage():
    from meridian.pipelines.deed_to_polygon import DeedParseError, parse_deed_text

    with pytest.raises(DeedParseError):
        parse_deed_text("This document is not a deed at all.")


def test_deed_distance_unknown_unit_raises():
    from meridian.pipelines.deed_to_polygon import DeedParseError, parse_distance

    with pytest.raises(DeedParseError):
        parse_distance("100 light_years")


# ── Traverse pipeline ─────────────────────────────────────────────────────


def test_traverse_with_no_observations_returns_no_legs(crs_local):
    from meridian.pipelines.traverse_adjust import reduce_setup_observations

    legs = reduce_setup_observations([], [])
    assert legs == []


def test_run_closed_traverse_unknown_method_raises():
    from meridian.pipelines.traverse_adjust import (
        TraverseLeg,
        run_closed_traverse,
    )

    leg = TraverseLeg(
        from_point="A", to_point="B", bearing=0.0,
        horizontal_distance=10.0, elevation_difference=0.0, setup_id="S1",
    )
    with pytest.raises(ValueError, match="Unknown adjustment method"):
        run_closed_traverse([leg], (0.0, 0.0), method="ouija_board")


# ── Boundary evidence ─────────────────────────────────────────────────────


def test_boundary_evidence_zero_pieces_raises():
    from meridian.jurisdictions.boundary_evidence import determine_boundary

    with pytest.raises(ValueError, match="at least one"):
        determine_boundary([], state="TX")


def test_boundary_evidence_single_piece_returns_that_piece():
    from meridian.jurisdictions.boundary_evidence import (
        BoundaryEvidence,
        EvidenceKind,
        determine_boundary,
    )

    only = BoundaryEvidence(
        id="solo", kind=EvidenceKind.NATURAL_MONUMENT,
        x=42.0, y=99.0, sigma_m=0.05,
    )
    det = determine_boundary([only], state="TX")
    assert det.x == pytest.approx(42.0)
    assert det.y == pytest.approx(99.0)


# ── Title commitment ──────────────────────────────────────────────────────


def test_title_commitment_handles_empty_text():
    from meridian.jurisdictions.title_commitment import parse_title_commitment

    c = parse_title_commitment("")
    assert c.requirements == ()
    assert c.exceptions == ()


def test_title_commitment_handles_only_schedule_a():
    from meridian.jurisdictions.title_commitment import parse_title_commitment

    text = "SCHEDULE A\nEffective Date: January 1, 2026\nFee Simple"
    c = parse_title_commitment(text)
    assert c.schedule_a.effective_date is not None
    assert c.requirements == ()
    assert c.exceptions == ()


# ── Chain of title ────────────────────────────────────────────────────────


def test_chain_of_title_zero_deeds_returns_empty():
    from meridian.jurisdictions.chain_of_title import build_chain

    chain = build_chain("parcel-x", [])
    assert chain.links == ()
    assert chain.defects == ()


def test_chain_of_title_deed_without_grantor_skipped():
    import datetime as dt

    from meridian.domain.deed import Deed, DeedKind, Party, PartyRole, Recording
    from meridian.jurisdictions.chain_of_title import build_chain

    deed = Deed(
        id="d1",
        kind=DeedKind.WARRANTY,
        # No grantor party.
        parties=(Party(name="Alice", role=PartyRole.GRANTEE),),
        recording=Recording(jurisdiction="X", recorded_date=dt.date(2026, 1, 1)),
    )
    chain = build_chain("p1", [deed])
    assert chain.links == ()


# ── PLSS ──────────────────────────────────────────────────────────────────


def test_plss_rejects_invalid_section_number():
    from meridian.jurisdictions.plss import section_corners

    with pytest.raises(ValueError, match=r"1\.\.36"):
        section_corners(0)
    with pytest.raises(ValueError, match=r"1\.\.36"):
        section_corners(37)


def test_plss_parser_handles_no_aliquot():
    from meridian.jurisdictions.plss import parse_plss

    desc = parse_plss("Section 14, T2N R3E, 6th P.M.")
    assert desc.aliquot is None


# ── Curve table ───────────────────────────────────────────────────────────


def test_curve_table_text_with_zero_curves():
    from meridian.adapters.reports.curve_table import write_curve_table_text

    text = write_curve_table_text([])
    # Header row should still print.
    assert "#" in text


def test_curve_data_rejects_negative_radius():
    from meridian.adapters.reports.curve_table import CurveData

    with pytest.raises(ValueError, match="positive"):
        CurveData.from_inputs(
            label="X", radius=-5.0, delta=1.0, chord_bearing=0.0, clockwise=True
        )


# ── Closure analysis ───────────────────────────────────────────────────────


def test_closure_with_two_legs_doesnt_crash():
    from meridian.adapters.reports.closure_report import analyze

    # Out-and-back: same line in opposite directions, perfect closure.
    report = analyze(bearings=[0.0, math.pi], distances=[10.0, 10.0])
    for m in report.methods:
        assert m.closure_m == pytest.approx(0.0, abs=1e-9)


# ── TruthChain ────────────────────────────────────────────────────────────


def test_truthchain_signed_identity_round_trip_preserves_payload():
    import datetime as dt

    from meridian.truthchain import SignedIdentity

    ident = SignedIdentity(
        surveyor_name="Test", license_state="TX", license_number="1",
        public_key_b64="abcd", issued_at=dt.datetime(2026, 5, 2, tzinfo=dt.UTC).isoformat(),
    )
    again = SignedIdentity.from_json(ident.to_json())
    assert again.surveyor_name == "Test"
    assert again.public_key_b64 == "abcd"


# ── CRS round-trip ─────────────────────────────────────────────────────────


def test_state_plane_label_is_useful():
    from meridian.domain.crs import state_plane

    crs = state_plane(2277)
    assert "EPSG:2277" in crs.label()


def test_unknown_utm_datum_raises():
    from meridian.domain.crs import utm

    with pytest.raises(ValueError, match="Unsupported"):
        utm(14, datum="MARS_2000")
