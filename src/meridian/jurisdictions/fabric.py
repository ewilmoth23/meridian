"""Parcel fabric — topologically-correct collection of parcels with shared edges.

A parcel fabric is the cadastral analogue of a planar graph: every parcel is
a closed walk through *shared* nodes and edges. When two parcels touch, they
reference the *same* edge object — so adjusting a node ripples through every
parcel that touches it. This is the foundation that lets you bring a survey
into agreement with neighbors without manually re-stitching every shared
boundary.

The fabric is an aggregate built on top of the immutable
:mod:`meridian.domain.geometry` primitives. Nodes / edges / parcels are
themselves frozen dataclasses; the :class:`ParcelFabric` container is
mutable but only via well-defined mutation methods that maintain topology
invariants.

Operations supported in this v0:

* ``add_parcel_from_ring`` — snap-tolerant insertion (existing nodes/edges
  within tolerance are reused, so a new parcel automatically *welds* itself
  to its neighbours).
* ``move_node`` — relocate a single node; every parcel it touches updates.
* ``remove_parcel`` — drop a parcel and garbage-collect orphaned
  nodes/edges.
* ``merge_parcels`` — combine 2+ contiguous parcels by removing the edges
  shared *only* among the merge group, then stitching the remaining outer
  edges into a single closed ring.
* ``split_parcel`` — split one parcel by a straight cut line.
* ``rubber_sheet`` — inverse-distance-weighted displacement field applied to
  every node (the standard "fit my fabric to control points" operation).
* ``topology_issues`` — detect duplicate nodes, overlapping parcels,
  self-intersecting rings.

Things deliberately deferred to a future iteration:

* Curved edges (arcs). v0 stores edges as straight line segments only.
* Parcels with interior holes. v0 stores a single outer ring per parcel.
* Persistent storage. v0 lives in memory; a SQLAlchemy adapter can wrap it.
* Spatial indexing. v0 is O(n) for nearest-node lookup which is fine for
  the target ~10⁴ parcels.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from enum import Enum

from meridian.domain.geometry import Point2D, Polygon

# ── Records ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FabricNode:
    """A 2D point shared by zero or more parcel corners."""

    id: str
    point: Point2D


@dataclass(frozen=True, slots=True)
class FabricEdge:
    """An undirected straight segment between two nodes.

    The edge has no inherent direction; the parcels that reference it
    declare the direction they traverse it (see :class:`EdgeRef`).
    """

    id: str
    node_a: str
    node_b: str

    def other(self, node_id: str) -> str:
        if node_id == self.node_a:
            return self.node_b
        if node_id == self.node_b:
            return self.node_a
        raise KeyError(f"Edge {self.id} does not touch node {node_id}.")


@dataclass(frozen=True, slots=True)
class EdgeRef:
    """A parcel's reference to an edge, with the direction it traverses it.

    ``forward=True`` means the parcel walks from ``edge.node_a`` to
    ``edge.node_b``; ``forward=False`` means the reverse.
    """

    edge_id: str
    forward: bool


@dataclass(frozen=True, slots=True)
class FabricParcel:
    """A parcel as an ordered closed walk of edge refs."""

    id: str
    name: str
    edge_refs: tuple[EdgeRef, ...]


class TopologyKind(str, Enum):
    DUPLICATE_NODE = "duplicate_node"
    OVERLAP = "overlap"
    SELF_INTERSECTION = "self_intersection"
    DEGENERATE_RING = "degenerate_ring"


@dataclass(frozen=True, slots=True)
class TopologyIssue:
    kind: TopologyKind
    description: str
    parcels: tuple[str, ...] = ()
    nodes: tuple[str, ...] = ()
    location: Point2D | None = None


# ── The fabric ──────────────────────────────────────────────────────────────


class ParcelFabric:
    """A mutable collection of parcels with shared nodes and edges.

    Parameters
    ----------
    snap_tolerance
        Distance below which two coordinates are treated as the same node
        (in the units of the fabric's CRS). 0.05 m / ~2 inches is a sensible
        default for projected survey work.

    """

    def __init__(self, *, snap_tolerance: float = 0.05) -> None:
        if snap_tolerance < 0:
            raise ValueError("snap_tolerance must be >= 0.")
        self._tol = float(snap_tolerance)
        self._nodes: dict[str, FabricNode] = {}
        self._edges: dict[str, FabricEdge] = {}
        self._parcels: dict[str, FabricParcel] = {}
        self._node_seq = itertools.count(1)
        self._edge_seq = itertools.count(1)

    # ── Read-only views ─────────────────────────────────────────────────────

    @property
    def snap_tolerance(self) -> float:
        return self._tol

    def nodes(self) -> tuple[FabricNode, ...]:
        return tuple(self._nodes.values())

    def edges(self) -> tuple[FabricEdge, ...]:
        return tuple(self._edges.values())

    def parcels(self) -> tuple[FabricParcel, ...]:
        return tuple(self._parcels.values())

    def node(self, node_id: str) -> FabricNode:
        return self._nodes[node_id]

    def edge(self, edge_id: str) -> FabricEdge:
        return self._edges[edge_id]

    def parcel(self, parcel_id: str) -> FabricParcel:
        return self._parcels[parcel_id]

    def __len__(self) -> int:
        return len(self._parcels)

    def __contains__(self, parcel_id: object) -> bool:
        return parcel_id in self._parcels

    # ── Lookup helpers ──────────────────────────────────────────────────────

    def find_node_at(self, p: Point2D) -> str | None:
        """Return the id of an existing node within ``snap_tolerance`` of ``p``,
        else ``None``. Linear scan; fine up to ~10⁴ nodes.
        """
        best_id: str | None = None
        best_d = self._tol
        for n in self._nodes.values():
            if n.point.crs != p.crs:
                continue
            d = math.hypot(n.point.x - p.x, n.point.y - p.y)
            if d <= best_d:
                best_d = d
                best_id = n.id
        return best_id

    def find_edge_between(self, node_a: str, node_b: str) -> str | None:
        """Return the id of the existing edge connecting these two nodes,
        regardless of orientation, else ``None``.
        """
        if node_a == node_b:
            return None
        for e in self._edges.values():
            if {e.node_a, e.node_b} == {node_a, node_b}:
                return e.id
        return None

    def parcels_using_edge(self, edge_id: str) -> tuple[str, ...]:
        return tuple(p.id for p in self._parcels.values() if any(r.edge_id == edge_id for r in p.edge_refs))

    def parcels_using_node(self, node_id: str) -> tuple[str, ...]:
        out: list[str] = []
        for p in self._parcels.values():
            for r in p.edge_refs:
                e = self._edges[r.edge_id]
                if node_id in (e.node_a, e.node_b):
                    out.append(p.id)
                    break
        return tuple(out)

    # ── Mutation: add ───────────────────────────────────────────────────────

    def add_parcel_from_ring(
        self,
        parcel_id: str,
        name: str,
        ring: list[Point2D] | tuple[Point2D, ...],
    ) -> FabricParcel:
        """Add a parcel whose boundary is the given closed (or implicitly closed)
        ring of points. Points within ``snap_tolerance`` of existing nodes are
        merged; edges between two existing nodes are reused.

        ``ring`` may be open (n points, n distinct corners) or closed (n+1
        points with the first repeated). Both forms are accepted.
        """
        if parcel_id in self._parcels:
            raise ValueError(f"Parcel {parcel_id!r} already exists.")
        pts = self._normalize_open_ring(ring)
        if len(pts) < 3:
            raise ValueError("Parcel ring needs at least 3 distinct corners.")
        crs = pts[0].crs
        for p in pts:
            if p.crs != crs:
                raise ValueError("All ring points must share a CRS.")

        # Snap each corner to an existing node or create a new one.
        node_ids: list[str] = []
        for p in pts:
            existing = self.find_node_at(p)
            if existing is not None:
                node_ids.append(existing)
            else:
                node_ids.append(self._add_node(p))

        # Reject degenerate rings (consecutive duplicates after snapping).
        for a, b in zip(node_ids, node_ids[1:] + node_ids[:1], strict=True):
            if a == b:
                raise ValueError(
                    "Parcel ring degenerated after snapping — two adjacent "
                    "corners collapsed to the same node. Increase corner "
                    "spacing or decrease snap_tolerance."
                )

        # Build edge refs, reusing existing edges where possible.
        refs: list[EdgeRef] = []
        for a, b in zip(node_ids, node_ids[1:] + node_ids[:1], strict=True):
            existing_edge = self.find_edge_between(a, b)
            if existing_edge is not None:
                edge = self._edges[existing_edge]
                refs.append(EdgeRef(edge_id=edge.id, forward=(edge.node_a == a)))
            else:
                edge = self._add_edge(a, b)
                refs.append(EdgeRef(edge_id=edge.id, forward=True))

        parcel = FabricParcel(id=parcel_id, name=name, edge_refs=tuple(refs))
        self._parcels[parcel_id] = parcel
        return parcel

    # ── Mutation: move / remove ─────────────────────────────────────────────

    def move_node(self, node_id: str, new_position: Point2D) -> None:
        """Relocate a node. Every parcel that touches it sees the change on
        its next :meth:`get_parcel_polygon` call.
        """
        old = self._nodes[node_id]
        if new_position.crs != old.point.crs:
            raise ValueError("New position CRS must match the existing node CRS.")
        self._nodes[node_id] = FabricNode(
            id=node_id,
            point=Point2D(
                x=new_position.x,
                y=new_position.y,
                crs=old.point.crs,
                name=old.point.name,
                description=old.point.description,
            ),
        )

    def remove_parcel(self, parcel_id: str) -> None:
        """Remove a parcel; orphaned nodes and edges are garbage-collected."""
        if parcel_id not in self._parcels:
            raise KeyError(parcel_id)
        del self._parcels[parcel_id]
        self._gc()

    def _gc(self) -> None:
        used_edges: set[str] = set()
        for p in self._parcels.values():
            for r in p.edge_refs:
                used_edges.add(r.edge_id)
        for eid in list(self._edges):
            if eid not in used_edges:
                del self._edges[eid]
        used_nodes: set[str] = set()
        for e in self._edges.values():
            used_nodes.add(e.node_a)
            used_nodes.add(e.node_b)
        for nid in list(self._nodes):
            if nid not in used_nodes:
                del self._nodes[nid]

    # ── Reconstruction ──────────────────────────────────────────────────────

    def get_parcel_polygon(self, parcel_id: str) -> Polygon:
        """Materialise the parcel's current boundary as a closed
        :class:`~meridian.domain.geometry.Polygon`.
        """
        ring_pts = self._walk_ring(self._parcels[parcel_id].edge_refs)
        # Polygon expects a closed ring (first point == last).
        closed = (*ring_pts, ring_pts[0])
        return Polygon(exterior=closed)

    def _walk_ring(self, refs: tuple[EdgeRef, ...]) -> tuple[Point2D, ...]:
        out: list[Point2D] = []
        for r in refs:
            e = self._edges[r.edge_id]
            start_node = e.node_a if r.forward else e.node_b
            out.append(self._nodes[start_node].point)
        return tuple(out)

    # ── Merge ───────────────────────────────────────────────────────────────

    def merge_parcels(
        self,
        parcel_ids: list[str] | tuple[str, ...],
        *,
        new_id: str,
        new_name: str,
    ) -> FabricParcel:
        """Merge two or more parcels into one. Every edge that is referenced
        *only* by parcels in the merge set (i.e. it's an internal shared
        boundary) is dropped; the remaining edges are stitched into a single
        outer ring.

        Raises ``ValueError`` if the merge group is not contiguous (the outer
        edges don't form a single closed walk).
        """
        ids = tuple(dict.fromkeys(parcel_ids))  # de-dup, preserve order
        if len(ids) < 2:
            raise ValueError("merge_parcels needs at least two parcel ids.")
        if new_id in self._parcels and new_id not in ids:
            raise ValueError(f"new_id {new_id!r} already in use.")
        for pid in ids:
            if pid not in self._parcels:
                raise KeyError(pid)

        merge_set = set(ids)
        # An edge is "internal" iff every parcel using it is in the merge set
        # AND at least two distinct parcels in the merge set use it.
        edge_users: dict[str, set[str]] = {}
        for pid in ids:
            for r in self._parcels[pid].edge_refs:
                edge_users.setdefault(r.edge_id, set()).add(pid)

        internal: set[str] = set()
        outer_refs: list[EdgeRef] = []
        for pid in ids:
            for r in self._parcels[pid].edge_refs:
                users = edge_users[r.edge_id]
                fully_external = bool(users - merge_set)
                if not fully_external and len(users) >= 2:
                    internal.add(r.edge_id)
                else:
                    outer_refs.append(r)

        # Stitch outer_refs into an ordered closed ring.
        ordered = self._stitch_ring(outer_refs)

        # Drop the merged parcels.
        for pid in ids:
            del self._parcels[pid]
        # Drop internal edges that are now unreferenced.
        for eid in internal:
            if not any(eid == r.edge_id for p in self._parcels.values() for r in p.edge_refs):
                self._edges.pop(eid, None)

        merged = FabricParcel(id=new_id, name=new_name, edge_refs=tuple(ordered))
        self._parcels[new_id] = merged
        self._gc()
        return merged

    def _stitch_ring(self, refs: list[EdgeRef]) -> list[EdgeRef]:
        """Order an unordered set of edge refs into a single closed walk.

        Uses a node-degree walk: each node must have exactly two incident
        edges in the ring; pick a start, follow incident edges in order.
        """
        if not refs:
            raise ValueError("Cannot stitch an empty edge set.")
        # Build adjacency: node_id -> list of (ref_index, ref)
        adj: dict[str, list[tuple[int, EdgeRef]]] = {}
        for idx, r in enumerate(refs):
            e = self._edges[r.edge_id]
            adj.setdefault(e.node_a, []).append((idx, r))
            adj.setdefault(e.node_b, []).append((idx, r))
        for node_id, incidents in adj.items():
            if len(incidents) != 2:
                raise ValueError(
                    f"Merge result is not a simple ring at node {node_id}: "
                    f"expected 2 incident edges, found {len(incidents)}. "
                    "The parcels are probably not contiguous."
                )

        used: set[int] = set()
        # Pick the first ref; orient it so we start from node_a.
        start_ref = refs[0]
        start_edge = self._edges[start_ref.edge_id]
        ordered: list[EdgeRef] = [EdgeRef(edge_id=start_ref.edge_id, forward=True)]
        used.add(0)
        current_node = start_edge.node_b

        while len(ordered) < len(refs):
            # Find the (unique) other incident edge at current_node.
            next_idx: int | None = None
            for idx, _r in adj[current_node]:
                if idx not in used:
                    next_idx = idx
                    break
            if next_idx is None:
                raise ValueError(
                    "Merge result is not a simple ring — outer edges form "
                    "more than one disjoint loop. The parcels are probably "
                    "not contiguous."
                )
            r = refs[next_idx]
            edge = self._edges[r.edge_id]
            forward = edge.node_a == current_node
            ordered.append(EdgeRef(edge_id=r.edge_id, forward=forward))
            used.add(next_idx)
            current_node = edge.node_b if forward else edge.node_a

        # Sanity: walk closed back to where we started?
        first_edge = self._edges[ordered[0].edge_id]
        first_start = first_edge.node_a if ordered[0].forward else first_edge.node_b
        if current_node != first_start:
            raise ValueError("Stitched ring did not close.")
        return ordered

    # ── Split ───────────────────────────────────────────────────────────────

    def split_parcel(
        self,
        parcel_id: str,
        cut: tuple[Point2D, Point2D],
        *,
        left_id: str,
        right_id: str,
        left_name: str,
        right_name: str,
    ) -> tuple[FabricParcel, FabricParcel]:
        """Split a parcel by a straight cut line that crosses its boundary at
        exactly two points.

        Each intersection inserts a new node (snapped to existing if within
        tolerance) and splits the affected edge into two. A new edge is added
        between the two intersection nodes; it becomes shared by both
        resulting parcels.
        """
        if parcel_id not in self._parcels:
            raise KeyError(parcel_id)
        if left_id == right_id:
            raise ValueError("left_id and right_id must differ.")
        if left_id in self._parcels or right_id in self._parcels:
            raise ValueError("Output parcel ids must not already exist.")

        a, b = cut
        if a.crs != b.crs:
            raise ValueError("Cut endpoints must share a CRS.")

        parcel = self._parcels[parcel_id]
        # Walk the ring as (corner_node_id, edge_id, forward) so we can
        # interleave intersections at the right spots.
        ring_seq: list[tuple[str, str, bool]] = []
        for r in parcel.edge_refs:
            e = self._edges[r.edge_id]
            start_node = e.node_a if r.forward else e.node_b
            ring_seq.append((start_node, r.edge_id, r.forward))

        # Find intersections of the cut line with each edge.
        intersections: list[tuple[int, float, Point2D]] = []  # (ring index, t along edge, point)
        for i, (_start_node, edge_id, forward) in enumerate(ring_seq):
            e = self._edges[edge_id]
            n_a = self._nodes[e.node_a].point
            n_b = self._nodes[e.node_b].point
            edge_p1 = n_a if forward else n_b
            edge_p2 = n_b if forward else n_a
            hit = _segment_intersection(edge_p1, edge_p2, a, b)
            if hit is None:
                continue
            t, pt = hit
            # Skip corner-coincident hits at t=0 to avoid double-counting at nodes.
            if t < 1e-9 or t > 1 - 1e-9:
                continue
            intersections.append((i, t, pt))

        if len(intersections) != 2:
            raise ValueError(
                f"Cut line must intersect the parcel boundary at exactly 2 "
                f"interior points; found {len(intersections)}."
            )
        intersections.sort(key=lambda x: x[0])  # stable, in ring order
        i1, _t1, pt1 = intersections[0]
        i2, _t2, pt2 = intersections[1]

        # Insert intersection nodes (snap if within tolerance).
        n1_id = self.find_node_at(pt1) or self._add_node(pt1)
        n2_id = self.find_node_at(pt2) or self._add_node(pt2)
        if n1_id == n2_id:
            raise ValueError("Cut intersection points collapse to the same node.")

        # Split each crossed edge in place.
        new_edge_ids = self._split_edge_at_node(ring_seq[i1][1], n1_id, ring_seq[i1][2])
        # Re-index i2 if it pointed at the same edge: we replaced one edge
        # with two, but only at i1, so i2 either points at a different
        # edge (no re-index needed) or at the original edge of i1 (which is
        # impossible because each cut crosses different edges if the parcel
        # is a simple ring). We require simple rings.
        if ring_seq[i2][1] == ring_seq[i1][1]:
            raise ValueError("Cut crosses the same edge twice — not supported.")
        new_edge_ids2 = self._split_edge_at_node(ring_seq[i2][1], n2_id, ring_seq[i2][2])

        # Add the cut edge.
        cut_edge = self._add_edge(n1_id, n2_id)

        # Now build the two new rings. Walk the original ring, splicing in
        # the new edges and the cut edge at the right places.
        left_refs, right_refs = self._build_split_rings(
            parcel,
            i1=i1,
            n1_id=n1_id,
            split_left_at_i1=new_edge_ids,
            i2=i2,
            n2_id=n2_id,
            split_left_at_i2=new_edge_ids2,
            cut_edge_id=cut_edge.id,
        )

        del self._parcels[parcel_id]
        left = FabricParcel(id=left_id, name=left_name, edge_refs=tuple(left_refs))
        right = FabricParcel(id=right_id, name=right_name, edge_refs=tuple(right_refs))
        self._parcels[left_id] = left
        self._parcels[right_id] = right
        self._gc()
        return left, right

    def _split_edge_at_node(self, edge_id: str, mid_node_id: str, forward: bool) -> tuple[str, str]:
        """Replace ``edge_id`` (between A and B) with two edges A→mid and mid→B.

        Returns ``(first_id, second_id)`` in the *forward* direction of the
        original parcel that called this. Updates every parcel that referenced
        the original edge.
        """
        old = self._edges.pop(edge_id)
        e1 = self._add_edge(old.node_a, mid_node_id)
        e2 = self._add_edge(mid_node_id, old.node_b)

        # Update every parcel that referenced the old edge: replace its single
        # ref with two refs in the right order.
        for pid, parcel in list(self._parcels.items()):
            new_refs: list[EdgeRef] = []
            mutated = False
            for r in parcel.edge_refs:
                if r.edge_id != edge_id:
                    new_refs.append(r)
                    continue
                mutated = True
                if r.forward:
                    new_refs.append(EdgeRef(edge_id=e1.id, forward=True))
                    new_refs.append(EdgeRef(edge_id=e2.id, forward=True))
                else:
                    new_refs.append(EdgeRef(edge_id=e2.id, forward=False))
                    new_refs.append(EdgeRef(edge_id=e1.id, forward=False))
            if mutated:
                self._parcels[pid] = FabricParcel(
                    id=parcel.id, name=parcel.name, edge_refs=tuple(new_refs)
                )

        # In the forward direction the order is (e1, e2).
        return (e1.id, e2.id) if forward else (e2.id, e1.id)

    def _build_split_rings(
        self,
        parcel: FabricParcel,
        *,
        i1: int,
        n1_id: str,
        split_left_at_i1: tuple[str, str],
        i2: int,
        n2_id: str,
        split_left_at_i2: tuple[str, str],
        cut_edge_id: str,
    ) -> tuple[list[EdgeRef], list[EdgeRef]]:
        # After the two _split_edge_at_node calls, parcel was already updated
        # in place. Re-fetch it and rebuild the two halves by walking from
        # n1 around to n2 (one half) and then around to n1 (the other), with
        # the cut edge bridging in each direction.
        updated = self._parcels[parcel.id]
        # Find indices of refs whose start-node is n1 / n2.
        starts: list[str] = []
        for r in updated.edge_refs:
            e = self._edges[r.edge_id]
            starts.append(e.node_a if r.forward else e.node_b)
        try:
            idx1 = starts.index(n1_id)
            idx2 = starts.index(n2_id)
        except ValueError as exc:
            raise ValueError("Failed to locate split nodes after edge split.") from exc

        n = len(updated.edge_refs)
        # First half: walk forward from idx1 up to (but not including) idx2.
        first: list[EdgeRef] = []
        i = idx1
        while i != idx2:
            first.append(updated.edge_refs[i])
            i = (i + 1) % n
        # Close with the cut edge from n2 back to n1.
        first.append(EdgeRef(edge_id=cut_edge_id, forward=False))

        # Second half: walk forward from idx2 up to (but not including) idx1.
        second: list[EdgeRef] = []
        i = idx2
        while i != idx1:
            second.append(updated.edge_refs[i])
            i = (i + 1) % n
        # Close with the cut edge from n1 to n2.
        second.append(EdgeRef(edge_id=cut_edge_id, forward=True))

        # Suppress unused-warning hints.
        _ = (split_left_at_i1, split_left_at_i2, i1, i2)
        return first, second

    # ── Rubber-sheet ────────────────────────────────────────────────────────

    def rubber_sheet(
        self,
        controls: list[tuple[Point2D, Point2D]] | tuple[tuple[Point2D, Point2D], ...],
        *,
        power: float = 2.0,
    ) -> None:
        """Apply an inverse-distance-weighted displacement field to every node.

        ``controls`` is a list of ``(source, target)`` point pairs. Every node
        is displaced by the weighted-average of the per-control displacements,
        with weights ``1 / max(d, eps)^power`` where ``d`` is the distance
        from the node to the *source* of that control.

        Notes
        -----
        * This is the simplest commercially-useful adjustment; it preserves
          control points exactly (zero-distance gets infinite weight).
        * For a small number of well-distributed controls (~3-10) over a
          single survey, this matches surveyor expectations: pull the corners
          to where they should be and the rest of the fabric follows.

        """
        if not controls:
            return
        if power <= 0:
            raise ValueError("power must be > 0.")
        crs = next(iter(self._nodes.values())).point.crs if self._nodes else None
        if crs is None:
            return
        for src, _tgt in controls:
            if src.crs != crs:
                raise ValueError("Control source CRS must match fabric CRS.")
        eps = max(self._tol, 1e-9)

        for nid, node in list(self._nodes.items()):
            p = node.point
            # If the node is exactly at a control source, pin to its target.
            pinned: Point2D | None = None
            for src, tgt in controls:
                if math.hypot(p.x - src.x, p.y - src.y) <= eps:
                    pinned = tgt
                    break
            if pinned is not None:
                self.move_node(nid, pinned)
                continue

            sum_w = 0.0
            sum_dx = 0.0
            sum_dy = 0.0
            for src, tgt in controls:
                d = max(math.hypot(p.x - src.x, p.y - src.y), eps)
                w = 1.0 / (d**power)
                sum_w += w
                sum_dx += w * (tgt.x - src.x)
                sum_dy += w * (tgt.y - src.y)
            new = Point2D(x=p.x + sum_dx / sum_w, y=p.y + sum_dy / sum_w, crs=p.crs, name=p.name, description=p.description)
            self.move_node(nid, new)

    # ── Validation ──────────────────────────────────────────────────────────

    def topology_issues(self) -> tuple[TopologyIssue, ...]:
        issues: list[TopologyIssue] = []

        # Duplicate nodes: any pair of nodes within tolerance of each other.
        node_list = list(self._nodes.values())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                a = node_list[i].point
                b = node_list[j].point
                if a.crs != b.crs:
                    continue
                if math.hypot(a.x - b.x, a.y - b.y) <= self._tol:
                    issues.append(
                        TopologyIssue(
                            kind=TopologyKind.DUPLICATE_NODE,
                            description=(
                                f"Nodes {node_list[i].id} and {node_list[j].id} "
                                f"are within snap tolerance ({self._tol})."
                            ),
                            nodes=(node_list[i].id, node_list[j].id),
                            location=a,
                        )
                    )

        # Self-intersection / degenerate ring per parcel.
        for parcel in self._parcels.values():
            try:
                ring = self._walk_ring(parcel.edge_refs)
            except KeyError:
                issues.append(
                    TopologyIssue(
                        kind=TopologyKind.DEGENERATE_RING,
                        description=f"Parcel {parcel.id} references missing edges.",
                        parcels=(parcel.id,),
                    )
                )
                continue
            if len(ring) < 3:
                issues.append(
                    TopologyIssue(
                        kind=TopologyKind.DEGENERATE_RING,
                        description=f"Parcel {parcel.id} has fewer than 3 corners.",
                        parcels=(parcel.id,),
                    )
                )
                continue
            if _ring_self_intersects(ring):
                issues.append(
                    TopologyIssue(
                        kind=TopologyKind.SELF_INTERSECTION,
                        description=f"Parcel {parcel.id} has a self-intersecting ring.",
                        parcels=(parcel.id,),
                    )
                )

        # Overlap: any pair of parcels with non-zero intersection area.
        parcel_polys: dict[str, Polygon] = {}
        for pid in self._parcels:
            try:
                parcel_polys[pid] = self.get_parcel_polygon(pid)
            except (ValueError, KeyError):
                continue
        ids = list(parcel_polys)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a_poly = parcel_polys[ids[i]]
                b_poly = parcel_polys[ids[j]]
                area = _polygon_overlap_area(a_poly, b_poly)
                # Small overlap may just be floating-point at shared edges; we
                # gate by snap_tolerance² as a rough planar threshold.
                if area > self._tol * self._tol:
                    issues.append(
                        TopologyIssue(
                            kind=TopologyKind.OVERLAP,
                            description=(
                                f"Parcels {ids[i]} and {ids[j]} overlap by "
                                f"{area:.4f} (in CRS units²)."
                            ),
                            parcels=(ids[i], ids[j]),
                        )
                    )
        return tuple(issues)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _add_node(self, p: Point2D) -> str:
        nid = f"n{next(self._node_seq)}"
        self._nodes[nid] = FabricNode(id=nid, point=p)
        return nid

    def _add_edge(self, node_a: str, node_b: str) -> FabricEdge:
        eid = f"e{next(self._edge_seq)}"
        edge = FabricEdge(id=eid, node_a=node_a, node_b=node_b)
        self._edges[eid] = edge
        return edge

    @staticmethod
    def _normalize_open_ring(ring: list[Point2D] | tuple[Point2D, ...]) -> list[Point2D]:
        pts = list(ring)
        if not pts:
            return pts
        # Drop the closing duplicate, if any.
        if (
            len(pts) >= 2
            and pts[0].x == pts[-1].x
            and pts[0].y == pts[-1].y
        ):
            pts = pts[:-1]
        return pts


# ── Geometry helpers ────────────────────────────────────────────────────────


def _segment_intersection(
    p1: Point2D, p2: Point2D, p3: Point2D, p4: Point2D
) -> tuple[float, Point2D] | None:
    """Intersect segment p1→p2 with segment p3→p4. Returns (t, point) where
    ``t`` is the parameter on p1→p2 of the intersection, or ``None`` if the
    segments are parallel / non-overlapping.
    """
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if not (0 <= t <= 1) or not (0 <= u <= 1):
        return None
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)
    return t, Point2D(x=px, y=py, crs=p1.crs)


def _ring_self_intersects(ring: tuple[Point2D, ...]) -> bool:
    """Detect self-intersection of an open polygon ring (n distinct corners)."""
    n = len(ring)
    for i in range(n):
        a1 = ring[i]
        a2 = ring[(i + 1) % n]
        for j in range(i + 1, n):
            # Skip adjacent edges (they share an endpoint legitimately).
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            b1 = ring[j]
            b2 = ring[(j + 1) % n]
            hit = _segment_intersection(a1, a2, b1, b2)
            if hit is None:
                continue
            _, pt = hit
            # Endpoint coincidences are acceptable; only flag interior hits.
            if (
                _close(pt, a1) or _close(pt, a2) or _close(pt, b1) or _close(pt, b2)
            ):
                continue
            return True
    return False


def _close(a: Point2D, b: Point2D, tol: float = 1e-9) -> bool:
    return math.hypot(a.x - b.x, a.y - b.y) <= tol


def _polygon_overlap_area(a: Polygon, b: Polygon) -> float:
    """Approximate the overlap area of two polygons by Sutherland-Hodgman
    clipping (b clipped against a).

    Convex-shape assumption: this is exact for convex parcels and an
    underestimate for non-convex. Good enough for fabric topology checks.
    """
    if a.crs != b.crs:
        return 0.0
    subject = list(b.exterior[:-1])
    clip = list(a.exterior[:-1])
    output = subject

    n_clip = len(clip)
    for ci in range(n_clip):
        if not output:
            break
        c1 = clip[ci]
        c2 = clip[(ci + 1) % n_clip]
        new_output: list[Point2D] = []
        n_out = len(output)
        for oi in range(n_out):
            current = output[oi]
            prev = output[oi - 1]
            curr_in = _is_inside(current, c1, c2)
            prev_in = _is_inside(prev, c1, c2)
            if curr_in:
                if not prev_in:
                    inter = _line_intersect(prev, current, c1, c2)
                    if inter is not None:
                        new_output.append(inter)
                new_output.append(current)
            elif prev_in:
                inter = _line_intersect(prev, current, c1, c2)
                if inter is not None:
                    new_output.append(inter)
        output = new_output

    if len(output) < 3:
        return 0.0
    area = 0.0
    n = len(output)
    for i in range(n):
        j = (i + 1) % n
        area += output[i].x * output[j].y - output[j].x * output[i].y
    return abs(area) / 2.0


def _is_inside(p: Point2D, c1: Point2D, c2: Point2D) -> bool:
    return (c2.x - c1.x) * (p.y - c1.y) - (c2.y - c1.y) * (p.x - c1.x) >= 0


def _line_intersect(p1: Point2D, p2: Point2D, p3: Point2D, p4: Point2D) -> Point2D | None:
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)
    return Point2D(x=px, y=py, crs=p1.crs)


# Keep public API discoverable.
__all__ = [
    "EdgeRef",
    "FabricEdge",
    "FabricNode",
    "FabricParcel",
    "ParcelFabric",
    "TopologyIssue",
    "TopologyKind",
]


# Reserve dataclass field hook for future extensibility (e.g. metadata
# attached to fabric records). Keep import order clean by re-exporting field.
_ = field
