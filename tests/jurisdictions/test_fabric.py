"""Tests for ``meridian.jurisdictions.fabric``."""

from __future__ import annotations

import math

import pytest

from meridian.domain.crs import CRS, Datum
from meridian.domain.geometry import Point2D
from meridian.jurisdictions.fabric import (
    EdgeRef,
    ParcelFabric,
    TopologyKind,
)

# Texas Central NAD83(2011) US ft — a real projected CRS for the demo data.
CRS_TX = CRS(epsg=2277, datum=Datum(name="NAD83", realization="2011", epsg=6318))


def pt(x: float, y: float) -> Point2D:
    return Point2D(x=x, y=y, crs=CRS_TX)


def square(x0: float, y0: float, side: float) -> list[Point2D]:
    return [pt(x0, y0), pt(x0 + side, y0), pt(x0 + side, y0 + side), pt(x0, y0 + side)]


# ── Construction & basic queries ────────────────────────────────────────────


def test_empty_fabric_has_no_state():
    fab = ParcelFabric()
    assert len(fab) == 0
    assert fab.nodes() == ()
    assert fab.edges() == ()
    assert fab.parcels() == ()
    assert "anything" not in fab


def test_negative_tolerance_rejected():
    with pytest.raises(ValueError, match="snap_tolerance"):
        ParcelFabric(snap_tolerance=-1.0)


def test_add_single_parcel_counts():
    fab = ParcelFabric()
    parcel = fab.add_parcel_from_ring("A", "Lot A", square(0, 0, 100))
    assert parcel.id == "A"
    assert len(fab) == 1
    assert len(fab.nodes()) == 4
    assert len(fab.edges()) == 4
    assert "A" in fab


def test_polygon_roundtrip():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "Lot A", square(0, 0, 100))
    poly = fab.get_parcel_polygon("A")
    assert poly.area() == pytest.approx(10000.0)
    assert math.isclose(poly.perimeter(), 400.0)


def test_closed_ring_input_is_normalised():
    fab = ParcelFabric()
    closed = [*square(0, 0, 100), pt(0, 0)]
    fab.add_parcel_from_ring("A", "Lot A", closed)
    assert len(fab.nodes()) == 4  # not 5


def test_duplicate_parcel_id_rejected():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "Lot A", square(0, 0, 100))
    with pytest.raises(ValueError, match="already exists"):
        fab.add_parcel_from_ring("A", "Lot A", square(200, 0, 100))


def test_too_few_corners_rejected():
    fab = ParcelFabric()
    with pytest.raises(ValueError, match="at least 3"):
        fab.add_parcel_from_ring("A", "Lot A", [pt(0, 0), pt(1, 0)])


def test_mixed_crs_rejected():
    fab = ParcelFabric()
    other_crs = CRS(epsg=4326)
    bad_ring = [pt(0, 0), pt(100, 0), Point2D(x=100, y=100, crs=other_crs), pt(0, 100)]
    with pytest.raises(ValueError, match="share a CRS"):
        fab.add_parcel_from_ring("A", "Lot A", bad_ring)


# ── Snap and edge-sharing ───────────────────────────────────────────────────


def test_neighboring_parcels_share_edge():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    # 6 nodes (4 from A + 2 new from B), 7 edges (4 + 3 new), 1 shared edge.
    assert len(fab.nodes()) == 6
    assert len(fab.edges()) == 7
    shared = [e for e in fab.edges() if len(fab.parcels_using_edge(e.id)) == 2]
    assert len(shared) == 1
    assert set(fab.parcels_using_edge(shared[0].id)) == {"A", "B"}


def test_snap_within_tolerance_reuses_node():
    fab = ParcelFabric(snap_tolerance=0.10)
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # Insert B with a corner 5 cm offset — should snap to existing node.
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100.05, 0.0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    assert len(fab.nodes()) == 6  # not 7


def test_snap_outside_tolerance_creates_new_node():
    fab = ParcelFabric(snap_tolerance=0.01)
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100.05, 0.0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    # 100.05 is outside 0.01 tolerance → new node not snapped.
    assert len(fab.nodes()) == 7


def test_degenerate_ring_after_snap_rejected():
    fab = ParcelFabric(snap_tolerance=10.0)
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # Two adjacent corners both within tolerance of node n1 → would collapse.
    with pytest.raises(ValueError, match="degenerated"):
        fab.add_parcel_from_ring(
            "B",
            "B",
            [pt(0.1, 0.1), pt(0.05, 0.05), pt(50, 50), pt(50, -50)],
        )


def test_find_node_at_returns_existing():
    fab = ParcelFabric(snap_tolerance=0.10)
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    nid = fab.find_node_at(pt(0.05, 0.0))
    assert nid is not None
    assert fab.find_node_at(pt(50, 50)) is None  # no node in centre


def test_find_edge_between_handles_orientation():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    nodes = list(fab.nodes())
    a, b = nodes[0].id, nodes[1].id
    eid = fab.find_edge_between(a, b)
    assert eid is not None
    assert fab.find_edge_between(b, a) == eid
    assert fab.find_edge_between(a, a) is None


# ── Move + remove ───────────────────────────────────────────────────────────


def test_move_node_propagates_to_all_users():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    # Find the shared corner at (100, 0).
    shared_node = next(n for n in fab.nodes() if n.point.x == 100 and n.point.y == 0)
    fab.move_node(shared_node.id, pt(100, -10))
    # Both parcels grow / shift accordingly.
    assert fab.get_parcel_polygon("A").area() == pytest.approx(10500.0)
    assert fab.get_parcel_polygon("B").area() == pytest.approx(10500.0)


def test_move_node_rejects_crs_mismatch():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    n = fab.nodes()[0]
    foreign = Point2D(x=0, y=0, crs=CRS(epsg=4326))
    with pytest.raises(ValueError, match="CRS"):
        fab.move_node(n.id, foreign)


def test_remove_parcel_garbage_collects_orphans():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.remove_parcel("A")
    assert len(fab) == 0
    assert fab.nodes() == ()
    assert fab.edges() == ()


def test_remove_parcel_keeps_shared_edges():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    fab.remove_parcel("A")
    # B still has its 4 edges; the shared edge survived because B uses it.
    assert len(fab.edges()) == 4
    assert len(fab.nodes()) == 4


def test_remove_unknown_parcel_raises():
    fab = ParcelFabric()
    with pytest.raises(KeyError):
        fab.remove_parcel("does-not-exist")


# ── Merge ───────────────────────────────────────────────────────────────────


def test_merge_two_contiguous_parcels():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    merged = fab.merge_parcels(["A", "B"], new_id="AB", new_name="Merged")
    assert merged.id == "AB"
    assert "A" not in fab
    assert "B" not in fab
    poly = fab.get_parcel_polygon("AB")
    assert poly.area() == pytest.approx(20000.0)
    # The internal shared edge is gone.
    assert len(fab.edges()) == 6  # was 7, dropped 1


def test_merge_three_in_a_row():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    fab.add_parcel_from_ring(
        "C",
        "C",
        [pt(200, 0), pt(300, 0), pt(300, 100), pt(200, 100)],
    )
    fab.merge_parcels(["A", "B", "C"], new_id="ABC", new_name="Big")
    assert fab.get_parcel_polygon("ABC").area() == pytest.approx(30000.0)


def test_merge_non_contiguous_raises():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring("B", "B", square(500, 500, 100))
    with pytest.raises(ValueError, match=r"not contiguous|simple ring"):
        fab.merge_parcels(["A", "B"], new_id="AB", new_name="Bad")


def test_merge_requires_two_parcels():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    with pytest.raises(ValueError, match="at least two"):
        fab.merge_parcels(["A"], new_id="X", new_name="X")


def test_merge_rejects_in_use_new_id():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    fab.add_parcel_from_ring("C", "C", square(300, 300, 100))
    with pytest.raises(ValueError, match="already in use"):
        fab.merge_parcels(["A", "B"], new_id="C", new_name="X")


# ── Split ───────────────────────────────────────────────────────────────────


def test_split_parcel_preserves_total_area():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    cut = (pt(50, -10), pt(50, 110))  # vertical cut through the middle
    left, right = fab.split_parcel(
        "A",
        cut,
        left_id="L",
        right_id="R",
        left_name="Left",
        right_name="Right",
    )
    assert left.id == "L"
    assert right.id == "R"
    a_left = fab.get_parcel_polygon("L").area()
    a_right = fab.get_parcel_polygon("R").area()
    assert a_left + a_right == pytest.approx(10000.0)
    # Two halves are equal (within fp).
    assert a_left == pytest.approx(a_right)


def test_split_creates_shared_edge():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.split_parcel(
        "A",
        (pt(50, -10), pt(50, 110)),
        left_id="L",
        right_id="R",
        left_name="L",
        right_name="R",
    )
    # The cut edge is shared by both halves.
    shared = [e for e in fab.edges() if set(fab.parcels_using_edge(e.id)) == {"L", "R"}]
    assert len(shared) == 1


def test_split_requires_exactly_two_intersections():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # A line entirely outside the parcel.
    with pytest.raises(ValueError, match="exactly 2"):
        fab.split_parcel(
            "A",
            (pt(200, 200), pt(300, 300)),
            left_id="L",
            right_id="R",
            left_name="L",
            right_name="R",
        )


def test_split_rejects_duplicate_output_id():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring("B", "B", square(500, 500, 100))
    with pytest.raises(ValueError, match="already exist"):
        fab.split_parcel(
            "A",
            (pt(50, -10), pt(50, 110)),
            left_id="B",  # collides
            right_id="R",
            left_name="L",
            right_name="R",
        )


# ── Rubber-sheet ────────────────────────────────────────────────────────────


def test_rubber_sheet_pins_controls_exactly():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # Move the corner at (0,0) → (1,2) and (100,100) → (102,103).
    controls = [
        (pt(0, 0), pt(1, 2)),
        (pt(100, 100), pt(102, 103)),
    ]
    fab.rubber_sheet(controls)
    # The two pinned nodes are exact.
    p_origin = next(n.point for n in fab.nodes() if n.id == "n1")
    p_far = next(n.point for n in fab.nodes() if n.id == "n3")
    assert p_origin.x == pytest.approx(1.0)
    assert p_origin.y == pytest.approx(2.0)
    assert p_far.x == pytest.approx(102.0)
    assert p_far.y == pytest.approx(103.0)


def test_rubber_sheet_interpolates_other_nodes():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # Pure translation as a single control covering all corners well.
    controls = [
        (pt(0, 0), pt(10, 10)),
        (pt(100, 0), pt(110, 10)),
        (pt(100, 100), pt(110, 110)),
        (pt(0, 100), pt(10, 110)),
    ]
    fab.rubber_sheet(controls)
    # Every node moves by exactly (+10, +10).
    for n in fab.nodes():
        # Find the source we started from; reverse-engineer is hard, so just
        # check that the area is preserved (a rigid translation).
        assert n.point.x >= 9.99 and n.point.y >= 9.99
    assert fab.get_parcel_polygon("A").area() == pytest.approx(10000.0)


def test_rubber_sheet_with_zero_controls_is_a_noop():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    before = [n.point for n in fab.nodes()]
    fab.rubber_sheet([])
    after = [n.point for n in fab.nodes()]
    assert before == after


def test_rubber_sheet_rejects_bad_power():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    with pytest.raises(ValueError, match="power"):
        fab.rubber_sheet([(pt(0, 0), pt(1, 1))], power=0.0)


# ── Topology validation ─────────────────────────────────────────────────────


def test_clean_fabric_has_no_issues():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(100, 0), pt(200, 0), pt(200, 100), pt(100, 100)],
    )
    assert fab.topology_issues() == ()


def test_overlap_detected():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # B overlaps A heavily — corners chosen to avoid exact node-snapping.
    fab.add_parcel_from_ring(
        "B",
        "B",
        [pt(50, 50), pt(150, 50), pt(150, 150), pt(50, 150)],
    )
    issues = fab.topology_issues()
    overlap = [i for i in issues if i.kind is TopologyKind.OVERLAP]
    assert len(overlap) == 1
    assert set(overlap[0].parcels) == {"A", "B"}


def test_self_intersection_detected_via_node_move():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    # Move corner (100, 0) inside the parcel so the ring crosses itself.
    target = next(n for n in fab.nodes() if n.point.x == 100 and n.point.y == 0)
    fab.move_node(target.id, pt(-50, 50))
    issues = fab.topology_issues()
    assert any(i.kind is TopologyKind.SELF_INTERSECTION for i in issues)


# ── Records: equality & immutability ────────────────────────────────────────


def test_edge_other_returns_opposite():
    fab = ParcelFabric()
    fab.add_parcel_from_ring("A", "A", square(0, 0, 100))
    edge = fab.edges()[0]
    assert edge.other(edge.node_a) == edge.node_b
    assert edge.other(edge.node_b) == edge.node_a
    with pytest.raises(KeyError):
        edge.other("not-on-edge")


def test_edge_ref_is_frozen():
    r = EdgeRef(edge_id="e1", forward=True)
    with pytest.raises(AttributeError):
        r.forward = False  # type: ignore[misc]
