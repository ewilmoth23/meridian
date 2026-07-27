"""Tests for ``meridian.jurisdictions.subdivision_design``."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS, Datum
from meridian.domain.geometry import Point2D, Polygon
from meridian.jurisdictions.fabric import ParcelFabric
from meridian.jurisdictions.subdivision_design import (
    DesignedLot,
    DesignIssue,
    LayoutKind,
    LotSpec,
    StreetSpec,
    SubdivisionDesign,
    buildable_envelope,
    design_rectangular_grid,
    design_strip,
    render_html,
    to_fabric,
    validate_design,
)

CRS_TX = CRS(epsg=2277, datum=Datum(name="NAD83", realization="2011", epsg=6318))


def pt(x: float, y: float) -> Point2D:
    return Point2D(x=x, y=y, crs=CRS_TX)


def rect(x0: float, y0: float, w: float, h: float) -> Polygon:
    return Polygon(exterior=(
        pt(x0, y0), pt(x0 + w, y0), pt(x0 + w, y0 + h), pt(x0, y0 + h), pt(x0, y0),
    ))


# ── LotSpec validation ──────────────────────────────────────────────────────


def test_lot_spec_requires_positive_dimensions():
    with pytest.raises(ValueError, match="min_area"):
        LotSpec(min_area=0, min_frontage=70, min_depth=120)
    with pytest.raises(ValueError, match="min_frontage"):
        LotSpec(min_area=8000, min_frontage=-1, min_depth=120)
    with pytest.raises(ValueError, match="min_depth"):
        LotSpec(min_area=8000, min_frontage=70, min_depth=0)


def test_lot_spec_setbacks_must_be_non_negative():
    with pytest.raises(ValueError, match="setback_front"):
        LotSpec(min_area=8000, min_frontage=70, min_depth=120, setback_front=-1)


def test_lot_spec_max_ratio_must_be_positive():
    with pytest.raises(ValueError, match="ratio"):
        LotSpec(
            min_area=8000, min_frontage=70, min_depth=120,
            max_depth_to_frontage_ratio=0,
        )


def test_street_spec_requires_positive_width():
    with pytest.raises(ValueError, match="row_width"):
        StreetSpec(row_width=0)


# ── design_strip ────────────────────────────────────────────────────────────


def test_strip_auto_count_fits_max_lots():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=10000, min_frontage=60, min_depth=120)
    design = design_strip(parent, spec)
    # 700/60 = 11 by frontage, but 700/11 × 150 = 9545 < min_area 10000.
    # Auto-reduce: 700/10 × 150 = 10500 ≥ 10000 ✓ → 10 lots.
    assert len(design.lots) == 10
    assert design.layout is LayoutKind.STRIP


def test_strip_auto_count_when_no_area_constraint_binding():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=60, min_depth=120)
    design = design_strip(parent, spec)
    # 700 / 60 = 11.67 → 11 lots; per-lot area 63.6×150 = 9545 ≥ 4000 ✓.
    assert len(design.lots) == 11


def test_strip_with_target_lots_widens_lot_frontage():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=10000, min_frontage=60, min_depth=120)
    design = design_strip(parent, spec, target_lots=7)
    assert len(design.lots) == 7
    expected_frontage = 700 / 7
    for lot in design.lots:
        assert lot.frontage_length == pytest.approx(expected_frontage)


def test_strip_target_too_many_raises():
    parent = rect(0, 0, 600, 150)
    spec = LotSpec(min_area=10000, min_frontage=80, min_depth=120)
    with pytest.raises(ValueError, match="frontage"):
        design_strip(parent, spec, target_lots=10)  # 60 < 80


def test_strip_too_shallow_parent_raises():
    parent = rect(0, 0, 700, 80)
    spec = LotSpec(min_area=10000, min_frontage=60, min_depth=120)
    with pytest.raises(ValueError, match="depth"):
        design_strip(parent, spec)


def test_strip_lot_areas_meet_spec():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=8000, min_frontage=60, min_depth=120)
    design = design_strip(parent, spec)
    for lot in design.lots:
        assert lot.area >= spec.min_area


def test_strip_west_facing_swaps_axes():
    parent = rect(0, 0, 200, 800)
    spec = LotSpec(min_area=8000, min_frontage=60, min_depth=120)
    design = design_strip(parent, spec, frontage_side="west")
    assert len(design.lots) == 800 // 60  # 13
    # All lots are 200-ft deep along the x-axis.
    for lot in design.lots:
        assert lot.depth_length == 200
        assert lot.frontage_length == pytest.approx(800 / 13)


# ── design_rectangular_grid ─────────────────────────────────────────────────


def test_grid_two_rows_share_central_street():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60, name="Maple Drive")
    design = design_rectangular_grid(parent, spec, street)
    # 800 / 70 = 11.4 → 11 lots/row, 22 total.
    assert len(design.lots) == 22
    assert len(design.streets) == 1
    # Each lot's depth = (400 - 60) / 2 = 170.
    for lot in design.lots:
        assert lot.depth_length == pytest.approx(170.0)


def test_grid_long_axis_auto_picks_longer_dim():
    wide = rect(0, 0, 800, 400)
    tall = rect(0, 0, 400, 800)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    d_wide = design_rectangular_grid(wide, spec, street)
    d_tall = design_rectangular_grid(tall, spec, street)
    # Both should yield the same lot count since the parents are rotations.
    assert len(d_wide.lots) == len(d_tall.lots)


def test_grid_too_narrow_raises():
    parent = rect(0, 0, 800, 200)  # only 200 deep, can't fit 2× 120 + 60 street
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    with pytest.raises(ValueError, match="short-axis"):
        design_rectangular_grid(parent, spec, street)


def test_grid_blocks_named_a_and_b():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    blocks = {lot.block for lot in design.lots}
    assert blocks == {"A", "B"}


def test_grid_target_lots_per_row_used_when_provided():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street, target_lots_per_row=8)
    assert len(design.lots) == 16


def test_grid_target_too_many_raises():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    with pytest.raises(ValueError, match="frontage"):
        design_rectangular_grid(parent, spec, street, target_lots_per_row=20)  # 40 < 70


def test_grid_invalid_long_axis_rejected():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    with pytest.raises(ValueError, match="long_axis"):
        design_rectangular_grid(parent, spec, street, long_axis="diagonal")


def test_grid_lots_dont_overlap_street():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    street_poly = design.streets[0].polygon
    # The street is centered on y=200 with width 60 → y in [170, 230].
    sb = street_poly.bbox()
    for lot in design.lots:
        lb = lot.polygon.bbox()
        # Lot bbox y-range must not overlap [170, 230] except at endpoints.
        assert lb.max_y <= sb.min_y + 1e-6 or lb.min_y >= sb.max_y - 1e-6


def test_grid_total_areas_sum_to_parent():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    assert design.total_lot_area + design.total_street_area == pytest.approx(parent.area())


# ── validate_design ─────────────────────────────────────────────────────────


def test_validate_clean_design_has_no_issues():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    assert validate_design(design) == ()


def test_validate_catches_undersized_lot_against_stricter_spec():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    stricter = LotSpec(min_area=15000, min_frontage=80, min_depth=120)
    issues = validate_design(design, spec=stricter)
    assert any("area" in i.message for i in issues)
    assert any("frontage" in i.message for i in issues)
    assert all(i.severity == "error" for i in issues if "area" in i.message)


def test_validate_warns_on_high_depth_to_frontage_ratio():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=40, min_depth=130)
    design = design_strip(parent, spec)
    stricter = LotSpec(
        min_area=4000, min_frontage=40, min_depth=130,
        max_depth_to_frontage_ratio=2.0,
    )
    issues = validate_design(design, spec=stricter)
    warnings = [i for i in issues if i.severity == "warning"]
    assert any("ratio" in w.message for w in warnings)


def test_validate_flags_no_buildable_envelope():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=40, min_depth=130)
    design = design_strip(parent, spec)
    too_deep = LotSpec(
        min_area=4000, min_frontage=40, min_depth=130,
        setback_front=80, setback_rear=80,  # 160 > 150 depth
    )
    issues = validate_design(design, spec=too_deep)
    assert any("buildable envelope" in i.message for i in issues)


# ── buildable_envelope ──────────────────────────────────────────────────────


def test_buildable_envelope_shrinks_lot_by_setbacks():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(
        min_area=4000, min_frontage=40, min_depth=120,
        setback_front=25, setback_rear=20, setback_side=10,
    )
    design = design_strip(parent, spec)
    lot = design.lots[0]
    env = buildable_envelope(lot)
    # Lot is ~63.6 wide × 150 deep; envelope is (63.6 - 20) × (150 - 45) = 43.6 × 105.
    assert env.area() == pytest.approx((lot.frontage_length - 20) * (lot.depth_length - 45))


def test_buildable_envelope_raises_when_setbacks_consume_lot():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=40, min_depth=120)
    design = design_strip(parent, spec)
    lot = design.lots[0]
    bad_setback_lot = DesignedLot(
        number=lot.number, block=lot.block, polygon=lot.polygon,
        frontage_length=lot.frontage_length, depth_length=lot.depth_length,
        front_edge=lot.front_edge,
        setbacks=LotSpec(
            min_area=4000, min_frontage=40, min_depth=120,
            setback_front=200, setback_rear=200, setback_side=200,
        ),
    )
    with pytest.raises(ValueError, match="buildable envelope"):
        buildable_envelope(bad_setback_lot)


# ── to_fabric ───────────────────────────────────────────────────────────────


def test_to_fabric_produces_clean_topology():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60, name="Maple Drive")
    design = design_rectangular_grid(parent, spec, street)
    fab = to_fabric(design)
    assert isinstance(fab, ParcelFabric)
    assert len(fab) == len(design.lots) + len(design.streets)
    assert fab.topology_issues() == ()


def test_to_fabric_lots_share_edges_with_neighbors():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60, name="Maple Drive")
    design = design_rectangular_grid(parent, spec, street)
    fab = to_fabric(design)
    # Find an edge shared between two adjacent lots in block A.
    a1_edges = {r.edge_id for r in fab.parcel("A-1").edge_refs}
    a2_edges = {r.edge_id for r in fab.parcel("A-2").edge_refs}
    shared = a1_edges & a2_edges
    assert len(shared) == 1


def test_to_fabric_strip_no_streets():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=40, min_depth=120)
    design = design_strip(parent, spec)
    fab = to_fabric(design)
    assert len(fab) == len(design.lots)
    assert fab.topology_issues() == ()


def test_to_fabric_propagates_node_moves_across_shared_edges():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60, name="Maple Drive")
    design = design_rectangular_grid(parent, spec, street)
    fab = to_fabric(design)
    # Move a node and confirm both touching parcels reflect it.
    n = fab.nodes()[0]
    moved = pt(n.point.x + 5, n.point.y + 5)
    users_before = fab.parcels_using_node(n.id)
    assert len(users_before) >= 1
    fab.move_node(n.id, moved)
    for pid in users_before:
        poly = fab.get_parcel_polygon(pid)
        # The moved point appears on at least one corner of every using parcel.
        assert any(
            abs(p.x - moved.x) < 1e-6 and abs(p.y - moved.y) < 1e-6
            for p in poly.exterior
        )


# ── render_html ─────────────────────────────────────────────────────────────


def test_render_html_includes_svg_and_schedule():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60, name="Maple Drive")
    design = design_rectangular_grid(parent, spec, street, name="Maple Heights")
    out = render_html(design)
    assert out.startswith("<!DOCTYPE html>")
    assert "<svg" in out
    assert "Maple Heights" in out
    assert "<polygon" in out
    assert "<table>" in out


def test_render_html_lists_validation_issues():
    parent = rect(0, 0, 700, 150)
    spec = LotSpec(min_area=4000, min_frontage=40, min_depth=120)
    design = design_strip(parent, spec)
    # Force a validation issue by injecting a stricter spec onto the design.
    stricter_design = SubdivisionDesign(
        name=design.name, layout=design.layout, parent=design.parent,
        lots=design.lots, streets=design.streets,
        spec=LotSpec(min_area=99999, min_frontage=40, min_depth=120),
    )
    out = render_html(stricter_design)
    assert "Issues" in out
    assert "ERROR" in out


# ── DesignIssue / dataclass behavior ───────────────────────────────────────


def test_design_issue_is_frozen():
    issue = DesignIssue(severity="error", lot_number="1", message="x")
    with pytest.raises(AttributeError):
        issue.severity = "warning"  # type: ignore[misc]


def test_subdivision_design_density_property():
    parent = rect(0, 0, 800, 400)
    spec = LotSpec(min_area=8000, min_frontage=70, min_depth=120)
    street = StreetSpec(row_width=60)
    design = design_rectangular_grid(parent, spec, street)
    expected = len(design.lots) / parent.area()
    assert design.density_lots_per_unit_area == pytest.approx(expected)
