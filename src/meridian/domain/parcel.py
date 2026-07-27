"""Parcel and call entities.

A parcel is a closed boundary made up of *calls*. A call is one of:
* a line — bearing + distance, or two points
* a curve — arc parameters or chord + curve data
* a tie — segment back to a known point (rarely used in deeds)

Calls are deed-level objects (a "call" reads as a clause in a legal
description). After running through :func:`meridian.pipelines.deed_to_polygon`
they produce a closed :class:`meridian.domain.geometry.Polygon`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point2D, Polygon


class CallKind(str, Enum):
    """The flavor of a call in a metes-and-bounds description."""

    LINE = "line"
    CURVE_ARC = "curve_arc"
    CURVE_CHORD = "curve_chord"
    POINT_OF_BEGINNING = "point_of_beginning"
    POINT_OF_TERMINATION = "point_of_termination"
    TIE = "tie"


@dataclass(frozen=True, slots=True)
class Call:
    """A single deed call.

    Attributes
    ----------
    kind
        Which flavour of call this is.
    bearing
        For LINE / TIE / CURVE_CHORD calls: bearing in **radians** measured
        clockwise from grid / true / magnetic north. ``None`` for arcs.
    distance
        For LINE / TIE / CURVE_CHORD: distance in **meters** internally.
        For CURVE_ARC: the arc length.
    radius
        Curve radius in meters (curves only).
    delta
        Central angle in radians (curves only).
    chord
        Chord length in meters (curves only — populated when known).
    clockwise
        Curve direction (curves only).
    monument
        Free-text monument description from the deed ("an iron pin found",
        "a 30-inch oak", "a stone marked W").
    notes
        Verbatim deed wording for this call (preserve the original).
    raw_index
        Position of this call in the source description (1-based).

    """

    kind: CallKind
    bearing: float | None = None
    distance: float | None = None
    radius: float | None = None
    delta: float | None = None
    chord: float | None = None
    clockwise: bool | None = None
    monument: str | None = None
    notes: str | None = None
    raw_index: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Boundary:
    """A computed boundary: the closed polygon plus a misclosure record.

    Produced by :func:`meridian.pipelines.deed_to_polygon.boundary_from_calls`.
    """

    polygon: Polygon
    misclosure_distance: float            # meters
    misclosure_bearing: float             # radians
    perimeter: float                      # meters
    closure_ratio: float                  # 1 / N (e.g. 1/15000)
    point_of_beginning: Point2D


@dataclass(frozen=True, slots=True)
class ParcelMetadata:
    """Bookkeeping for a parcel — does not affect geometry."""

    parcel_id: str | None = None          # external/jurisdiction id
    apn: str | None = None                # tax assessor parcel number
    legal_description_text: str | None = None
    description_source: str | None = None # deed reference / file name
    recording: str | None = None          # "Vol. 234, Pg. 56"
    recorded_date: dt.date | None = None
    grantor: str | None = None
    grantee: str | None = None
    acreage: float | None = None          # stated in deed
    address: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Parcel:
    """A surveyed (or to-be-surveyed) tract of land.

    A parcel always has a CRS — when constructed from a deed before any
    georeferencing, the CRS is the *assumed* local CRS (typically a
    placeholder ``CRS`` flagged as ``assumed``).
    """

    name: str
    crs: CRS
    calls: tuple[Call, ...]
    boundary: Boundary | None = None
    metadata: ParcelMetadata = field(default_factory=ParcelMetadata)
