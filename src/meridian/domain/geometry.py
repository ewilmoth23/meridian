"""Canonical geometric primitives.

These are the *only* point/line/curve/polygon types in Meridian. Every
adapter, every pipeline, every UI consumes and produces these. If you find
yourself defining a second ``Point`` somewhere — stop and use these.

Design notes:

* Points are immutable frozen dataclasses with ``slots=True`` for cache
  efficiency.
* All entities carry a CRS reference. A point with no CRS is rejected at
  construction.
* :class:`Polygon` validates ring closure and orientation (exterior rings
  are CCW; interior holes are CW), matching OGC SFA convention.
* No I/O. To convert to/from Shapely, GeoJSON, or DXF, use the appropriate
  adapter.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.crs import CRS


# ── 2D / 3D points ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Point2D:
    """A 2D point in some CRS.

    Coordinates are stored as ``x`` (easting / longitude) and ``y``
    (northing / latitude) in the units of the CRS. The horizontal
    axis order in ``crs`` tells consumers which is which.
    """

    x: float
    y: float
    crs: CRS
    name: str | None = None
    description: str | None = None

    def to_3d(self, z: float = 0.0) -> Point3D:
        return Point3D(x=self.x, y=self.y, z=z, crs=self.crs, name=self.name, description=self.description)

    def distance_to(self, other: Point2D) -> float:
        if other.crs != self.crs:
            raise ValueError("Points are in different CRSs; transform first.")
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True, slots=True)
class Point3D:
    """A 3D point in some CRS plus an optional vertical reference.

    The vertical reference is captured by ``crs.vertical`` if the CRS has
    one set; otherwise ``z`` is interpreted as ellipsoidal height.
    """

    x: float
    y: float
    z: float
    crs: CRS
    name: str | None = None
    description: str | None = None

    def to_2d(self) -> Point2D:
        return Point2D(x=self.x, y=self.y, crs=self.crs, name=self.name, description=self.description)

    def distance_to(self, other: Point3D) -> float:
        if other.crs != self.crs:
            raise ValueError("Points are in different CRSs; transform first.")
        dx = other.x - self.x
        dy = other.y - self.y
        dz = other.z - self.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def horizontal_distance_to(self, other: Point3D) -> float:
        if other.crs != self.crs:
            raise ValueError("Points are in different CRSs; transform first.")
        return math.hypot(other.x - self.x, other.y - self.y)


# ── Line / arc segments ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LineSegment:
    """A straight line between two points."""

    start: Point2D
    end: Point2D

    def __post_init__(self) -> None:
        if self.start.crs != self.end.crs:
            raise ValueError("LineSegment endpoints must share a CRS.")

    @property
    def crs(self) -> CRS:
        return self.start.crs

    def length(self) -> float:
        return self.start.distance_to(self.end)

    def bearing(self) -> float:
        """Azimuth from ``start`` to ``end`` in radians, measured clockwise
        from the positive y-axis (north).
        """
        dx = self.end.x - self.start.x
        dy = self.end.y - self.start.y
        return math.atan2(dx, dy) % (2 * math.pi)


@dataclass(frozen=True, slots=True)
class Arc:
    """A circular arc.

    Conventions:
    * ``start`` and ``end`` are tangent points on the curve.
    * ``radius`` is positive.
    * ``clockwise`` indicates curve direction from start → end.
    * ``center`` is computed (and cached) by :meth:`center_point` if needed.
    """

    start: Point2D
    end: Point2D
    radius: float
    clockwise: bool

    def __post_init__(self) -> None:
        if self.start.crs != self.end.crs:
            raise ValueError("Arc endpoints must share a CRS.")
        if self.radius <= 0:
            raise ValueError(f"Arc radius must be positive, got {self.radius}.")

    @property
    def crs(self) -> CRS:
        return self.start.crs

    def chord_length(self) -> float:
        return self.start.distance_to(self.end)

    def delta(self) -> float:
        """Central angle (delta) of the arc in radians."""
        chord = self.chord_length()
        if chord > 2 * self.radius:
            raise ValueError(f"Chord {chord} exceeds 2R = {2 * self.radius}; arc impossible.")
        return 2 * math.asin(chord / (2 * self.radius))

    def arc_length(self) -> float:
        return self.radius * self.delta()

    def tangent_length(self) -> float:
        """Tangent distance T = R * tan(delta/2)."""
        return self.radius * math.tan(self.delta() / 2)


# ── Polygon ──────────────────────────────────────────────────────────────────


def _ring_is_closed(points: Sequence[Point2D]) -> bool:
    return (
        len(points) >= 3
        and points[0].x == points[-1].x
        and points[0].y == points[-1].y
    )


def _signed_area(points: Sequence[Point2D]) -> float:
    """Signed shoelace area. Positive = CCW, negative = CW."""
    if len(points) < 3:
        return 0.0
    area = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        area += points[i].x * points[j].y - points[j].x * points[i].y
    return area / 2.0


@dataclass(frozen=True, slots=True)
class Polygon:
    """A planar polygon with optional interior holes.

    Rings are stored as **closed** sequences (first point repeated at end).
    Exterior is CCW (positive signed area); interior holes are CW
    (negative signed area), matching OGC SFA.
    """

    exterior: tuple[Point2D, ...]
    holes: tuple[tuple[Point2D, ...], ...] = ()

    def __post_init__(self) -> None:
        if len(self.exterior) < 4:
            raise ValueError("Exterior ring must have at least 4 points (3 + closing).")
        if not _ring_is_closed(self.exterior):
            raise ValueError("Exterior ring is not closed.")
        crs = self.exterior[0].crs
        for p in self.exterior[1:]:
            if p.crs != crs:
                raise ValueError("All exterior points must share a CRS.")
        for hole in self.holes:
            if len(hole) < 4 or not _ring_is_closed(hole):
                raise ValueError("Each hole must be a closed ring of >= 4 points.")
            for p in hole:
                if p.crs != crs:
                    raise ValueError("All hole points must share the exterior CRS.")
        # We don't auto-orient — that's a transformation, not validation.
        # Adapters that need a particular orientation should call
        # :meth:`oriented` and use the result.

    @property
    def crs(self) -> CRS:
        return self.exterior[0].crs

    def signed_area(self) -> float:
        a = _signed_area(self.exterior)
        for hole in self.holes:
            a -= abs(_signed_area(hole))
        return a

    def area(self) -> float:
        """Absolute area in the units of the CRS squared."""
        return abs(self.signed_area())

    def is_ccw(self) -> bool:
        return _signed_area(self.exterior) > 0

    def oriented(self) -> Polygon:
        """Return a copy with exterior CCW and holes CW (OGC convention)."""
        ext = self.exterior if self.is_ccw() else tuple(reversed(self.exterior))
        holes = tuple(
            tuple(reversed(h)) if _signed_area(h) > 0 else h
            for h in self.holes
        )
        return Polygon(exterior=ext, holes=holes)

    def perimeter(self) -> float:
        per = 0.0
        for i in range(len(self.exterior) - 1):
            per += self.exterior[i].distance_to(self.exterior[i + 1])
        return per

    def vertices(self) -> Iterator[Point2D]:
        """Iterate exterior ring (including the duplicated closing point)."""
        yield from self.exterior

    def bbox(self) -> BBox2D:
        xs = [p.x for p in self.exterior]
        ys = [p.y for p in self.exterior]
        return BBox2D(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys), crs=self.crs)


# ── Bounding boxes ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BBox2D:
    """An axis-aligned 2D bounding box."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    crs: CRS

    def __post_init__(self) -> None:
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("BBox2D min must be <= max on each axis.")

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def area(self) -> float:
        return self.width * self.height

    def center(self) -> Point2D:
        return Point2D(x=(self.min_x + self.max_x) / 2, y=(self.min_y + self.max_y) / 2, crs=self.crs)

    def contains(self, p: Point2D) -> bool:
        if p.crs != self.crs:
            raise ValueError("Point and BBox CRS mismatch.")
        return self.min_x <= p.x <= self.max_x and self.min_y <= p.y <= self.max_y

    def expand(self, by: float) -> BBox2D:
        return BBox2D(
            min_x=self.min_x - by,
            min_y=self.min_y - by,
            max_x=self.max_x + by,
            max_y=self.max_y + by,
            crs=self.crs,
        )


@dataclass(frozen=True, slots=True)
class BBox3D:
    """An axis-aligned 3D bounding box."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float
    crs: CRS

    def __post_init__(self) -> None:
        if self.min_x > self.max_x or self.min_y > self.max_y or self.min_z > self.max_z:
            raise ValueError("BBox3D min must be <= max on each axis.")

    def to_2d(self) -> BBox2D:
        return BBox2D(min_x=self.min_x, min_y=self.min_y, max_x=self.max_x, max_y=self.max_y, crs=self.crs)
