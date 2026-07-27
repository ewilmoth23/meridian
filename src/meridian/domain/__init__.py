"""Canonical domain entities for Meridian.

This package contains the **single, authoritative** definitions of the entities
that flow through every other layer: points, observations, parcels, deeds,
surveys, point clouds, and coordinate reference systems.

Hard rules for this package:

1. No I/O. No ``open()``, no ``sqlite3``, no ``requests``, no ``Qt``.
2. No imports from ``meridian.adapters``, ``meridian.services``, or any
   other layer. Domain depends on the standard library, ``numpy``, and
   ``pyproj`` (for CRS metadata only — not transformations).
3. Every entity is immutable by default (``frozen=True`` dataclasses, or
   ``attrs.frozen``) unless an explicit mutable use case demands otherwise.
4. No file-format-specific fields. Layer names, DXF colors, GeoJSON
   properties belong on the **adapter** representation, not here.
"""

from __future__ import annotations

from meridian.domain.crs import CRS, Datum, Geoid, Projection, VerticalDatum
from meridian.domain.geometry import (
    Arc,
    BBox2D,
    BBox3D,
    LineSegment,
    Point2D,
    Point3D,
    Polygon,
)
from meridian.domain.observation import (
    AdjustedObservation,
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.domain.parcel import Boundary, Call, CallKind, Parcel
from meridian.domain.survey import Survey, SurveyProject

__all__ = [
    "CRS",
    "AdjustedObservation",
    "Arc",
    "BBox2D",
    "BBox3D",
    "Boundary",
    "Call",
    "CallKind",
    "Datum",
    "Geoid",
    "LineSegment",
    "ObservationKind",
    "Parcel",
    "Point2D",
    "Point3D",
    "Polygon",
    "Projection",
    "RawObservation",
    "Setup",
    "Survey",
    "SurveyProject",
    "VerticalDatum",
]
