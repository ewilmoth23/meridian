"""CoStake CRDT tests — convergence under concurrent edits."""

from __future__ import annotations

from meridian.costake.geometry_crdt import GeometryCRDT, OpKind, PolygonOp, apply_op
from meridian.costake.lww import LWWMap, LWWRegister, LWWStamp

# ── LWW ─────────────────────────────────────────────────────────────────────


def test_lww_register_newer_write_wins():
    a = LWWRegister(actor="A")
    b = LWWRegister(actor="B")
    a.set("alice")
    b.set("bob")  # ts is later → b wins on merge into a
    a.merge(b.value, b.stamp)
    assert a.value == "bob"


def test_lww_register_actor_breaks_tie():
    s1 = LWWStamp(ts=100, actor="A")
    s2 = LWWStamp(ts=100, actor="B")
    assert s1 < s2


def test_lww_map_converges_under_disjoint_keys():
    a = LWWMap(actor="A")
    b = LWWMap(actor="B")
    a.set("name", "Tract A")
    b.set("apn", "TX-001")
    a.merge(b)
    b.merge(a)
    # Compare values+stamps via items(); the local-writer actor field on
    # each register is identity, not part of the merged state.
    assert dict(a.items()) == dict(b.items())
    for key in ("name", "apn"):
        assert a.cells[key].stamp == b.cells[key].stamp
    assert a.get("name") == "Tract A"
    assert a.get("apn") == "TX-001"
    assert b.get("name") == "Tract A"
    assert b.get("apn") == "TX-001"


# ── Geometry CRDT ──────────────────────────────────────────────────────────


def test_inserts_and_moves_apply():
    crdt = GeometryCRDT(actor="A")
    crdt.insert("v1", (0.0, 0.0), after=None)
    crdt.insert("v2", (10.0, 0.0), after="v1")
    crdt.insert("v3", (10.0, 10.0), after="v2")
    crdt.move("v2", (10.5, 0.5))
    assert crdt.order == ["v1", "v2", "v3"]
    assert crdt.coords["v2"] == (10.5, 0.5)


def test_concurrent_inserts_converge():
    a = GeometryCRDT(actor="A")
    b = GeometryCRDT(actor="B")

    op1 = a.insert("v1", (0.0, 0.0), after=None)
    op2 = a.insert("v2", (1.0, 0.0), after="v1")

    # Replay A's ops on B
    b.merge_op(op1)
    b.merge_op(op2)

    # Now both edit concurrently
    op3 = a.insert("v3", (2.0, 0.0), after="v2")
    op4 = b.insert("v4", (1.5, 0.5), after="v2")

    a.merge_op(op4)
    b.merge_op(op3)

    assert a.order == b.order
    assert a.coords == b.coords


def test_concurrent_move_lww_resolves():
    a = GeometryCRDT(actor="A")
    b = GeometryCRDT(actor="B")
    op1 = a.insert("v1", (0.0, 0.0), after=None)
    b.merge_op(op1)
    op_a = a.move("v1", (1.0, 1.0))
    op_b = b.move("v1", (2.0, 2.0))
    a.merge_op(op_b)
    b.merge_op(op_a)
    # The later timestamp wins; both peers agree.
    assert a.coords["v1"] == b.coords["v1"]


def test_delete_creates_tombstone():
    a = GeometryCRDT(actor="A")
    a.insert("v1", (0.0, 0.0), after=None)
    a.delete("v1")
    assert "v1" in a.tombstones
    assert "v1" not in a.coords
    # A late-arriving move should be ignored.
    op = PolygonOp(kind=OpKind.MOVE, vertex_id="v1", coords=(9.0, 9.0), actor="B", ts=10**18)
    apply_op(a, op)
    assert "v1" not in a.coords
