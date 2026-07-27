"""Geometry-aware CRDT for collaborative parcel editing.

Inspired by *Geometry-Aware CRDTs for Collaborative Geospatial Editing*
(MDPI IJGI 14(12) 468, 2025). The core insight: don't try to merge raw
vertex lists — instead, track named vertices with stable ids and treat
the polygon as a *sequence of vertex ids* with insert/delete/move
operations. Then concurrent edits commute the same way list-based
CRDTs do.

For Meridian v0.1 of CoStake we ship:

* Named vertex pool with LWW-Register coordinates per id.
* Ordered ring of vertex ids managed as an LWW-element-sequence.
* Move-vertex op = LWW-set on the vertex's coordinate.
* Insert/delete-vertex ops use a position-based RGA-style id allocation.

The actual operational-transform / Yjs interop layer lives in
``meridian.costake.transport`` (next).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from meridian.costake.lww import LWWStamp, _now_ns


class OpKind(str, Enum):
    INSERT = "insert"
    DELETE = "delete"
    MOVE = "move"


@dataclass(frozen=True, slots=True)
class PolygonOp:
    """One CRDT operation over a polygon boundary."""

    kind: OpKind
    vertex_id: str
    after_id: str | None = None       # for INSERT — predecessor in the ring
    coords: tuple[float, float] | None = None
    actor: str = ""
    ts: int = field(default_factory=_now_ns)

    def stamp(self) -> LWWStamp:
        return LWWStamp(ts=self.ts, actor=self.actor)


@dataclass(slots=True)
class GeometryCRDT:
    """A single polygon's collaborative state.

    Internally stores:
    * ``order`` — the visible ring as a list of vertex ids.
    * ``coords`` — vertex_id → (x, y) at last known good coordinates.
    * ``stamps`` — vertex_id → LWWStamp of its last move.
    * ``tombstones`` — set of deleted vertex ids; ops referencing them
      are silently dropped to keep convergence stable.
    """

    actor: str
    order: list[str] = field(default_factory=list)
    coords: dict[str, tuple[float, float]] = field(default_factory=dict)
    stamps: dict[str, LWWStamp] = field(default_factory=dict)
    tombstones: set[str] = field(default_factory=set)
    history: list[PolygonOp] = field(default_factory=list)

    def insert(self, vertex_id: str, coords: tuple[float, float], *, after: str | None) -> PolygonOp:
        op = PolygonOp(
            kind=OpKind.INSERT,
            vertex_id=vertex_id,
            after_id=after,
            coords=coords,
            actor=self.actor,
        )
        apply_op(self, op)
        return op

    def move(self, vertex_id: str, coords: tuple[float, float]) -> PolygonOp:
        op = PolygonOp(
            kind=OpKind.MOVE, vertex_id=vertex_id, coords=coords, actor=self.actor
        )
        apply_op(self, op)
        return op

    def delete(self, vertex_id: str) -> PolygonOp:
        op = PolygonOp(kind=OpKind.DELETE, vertex_id=vertex_id, actor=self.actor)
        apply_op(self, op)
        return op

    def merge_op(self, op: PolygonOp) -> bool:
        """Apply a remote op. Returns True if it changed local state."""
        return apply_op(self, op)


def apply_op(crdt: GeometryCRDT, op: PolygonOp) -> bool:
    """Mutate ``crdt`` by ``op`` idempotently and convergently."""
    if op.vertex_id in crdt.tombstones and op.kind != OpKind.DELETE:
        return False

    if op.kind == OpKind.INSERT:
        if op.coords is None:
            return False
        if op.vertex_id in crdt.coords:
            return False
        # RGA-style insertion: if multiple ops target the same anchor,
        # order them deterministically by their stamps so peers converge
        # regardless of arrival order. Newer-stamped concurrent inserts
        # sit further from the anchor.
        op_stamp = op.stamp()
        if op.after_id is None or op.after_id not in crdt.order:
            base_idx = len(crdt.order)
        else:
            base_idx = crdt.order.index(op.after_id) + 1
        idx = base_idx
        while idx < len(crdt.order):
            sibling = crdt.order[idx]
            sibling_stamp = crdt.stamps.get(sibling)
            if sibling_stamp is None or op_stamp < sibling_stamp:
                break
            idx += 1
        crdt.order.insert(idx, op.vertex_id)
        crdt.coords[op.vertex_id] = op.coords
        crdt.stamps[op.vertex_id] = op_stamp
        crdt.history.append(op)
        return True

    if op.kind == OpKind.MOVE:
        if op.coords is None or op.vertex_id not in crdt.coords:
            return False
        prev = crdt.stamps.get(op.vertex_id)
        if prev is not None and not (prev < op.stamp()):
            return False
        crdt.coords[op.vertex_id] = op.coords
        crdt.stamps[op.vertex_id] = op.stamp()
        crdt.history.append(op)
        return True

    if op.kind == OpKind.DELETE:
        if op.vertex_id in crdt.tombstones:
            return False
        crdt.tombstones.add(op.vertex_id)
        if op.vertex_id in crdt.order:
            crdt.order.remove(op.vertex_id)
        crdt.coords.pop(op.vertex_id, None)
        crdt.stamps.pop(op.vertex_id, None)
        crdt.history.append(op)
        return True

    return False
