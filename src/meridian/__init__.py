"""Meridian — the modern surveyor's suite.

Public API surface (re-exports of the most-used domain types).
Adapters and services are imported directly from their submodules.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Domain re-exports — the canonical types used by every other layer.
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
    "__version__",
    # CRS
    "CRS",
    "Datum",
    "Projection",
    "Geoid",
    "VerticalDatum",
    # Geometry
    "Point2D",
    "Point3D",
    "LineSegment",
    "Arc",
    "Polygon",
    "BBox2D",
    "BBox3D",
    # Observations
    "RawObservation",
    "AdjustedObservation",
    "Setup",
    "ObservationKind",
    # Parcel
    "Parcel",
    "Boundary",
    "Call",
    "CallKind",
    # Survey
    "Survey",
    "SurveyProject",
]
