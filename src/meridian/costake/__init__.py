"""CoStake — Google-Docs-style real-time co-editing (v0.8).

Geometry-aware CRDTs for concurrent editing of survey data. Two
surveyors edit the same project; each sees the other's cursor, edits,
and saves in <100 ms; conflict-free on calls, parcels, observations,
and adjustments.

Status: planning stub for v0.8.

Components (to be implemented):

* ``crdt/yjs_bridge.py`` — Yjs-based CRDT for non-geometry fields
  (names, descriptions, metadata).
* ``crdt/geometry_crdt.py`` — custom CRDT inspired by *Geometry-Aware
  CRDTs for Collaborative Geospatial Editing* (MDPI IJGI 14(12) 468,
  2025) for parcel topology and adjusted-coordinate updates.
* ``transport/websocket.py`` — WebSocket transport with presence info.
* ``presence/cursors.py`` — per-user cursor and selection state.
* ``conflict/policies.py`` — deterministic resolution policies for the
  small number of operations that are not natively CRDT-mergeable
  (e.g., re-orienting a polygon).
* ``server/relay.py`` — light Y-Sweet / y-websocket-compatible relay,
  optional self-hosting.

Why this is a moat:
* No production surveying / GIS / CAD tool ships true CRDT-based
  concurrent editing in 2026. The literature is mature enough to
  productize. Trimble Connect, Bentley iTwin, Autodesk Construction
  Cloud, Carlson Cloud, MAGNET Enterprise are all file-share + comment.
"""

from __future__ import annotations

from meridian.costake.geometry_crdt import (
    GeometryCRDT,
    PolygonOp,
    apply_op,
)
from meridian.costake.lww import LWWMap, LWWRegister
from meridian.costake.presence import Cursor, PresenceState
from meridian.costake.relay import CoStakeRelay

__all__ = [
    "CoStakeRelay",
    "Cursor",
    "GeometryCRDT",
    "LWWMap",
    "LWWRegister",
    "PolygonOp",
    "PresenceState",
    "apply_op",
]
