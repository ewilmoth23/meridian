"""Point-cloud and surface entities.

We *do not* hold full point clouds in memory in domain dataclasses — at
billion-point scale that's not viable. Instead :class:`PointCloud` is a
**reference** to data on disk (LAS/LAZ/COPC) plus the metadata needed to
plan operations against it.

Heavy operations (classification, filtering, TIN, contour) run inside
:mod:`meridian.adapters.pointcloud.pdal_pipeline` against PDAL pipelines
or laspy chunked readers. The output of those operations comes back as
either (a) another on-disk :class:`PointCloud` or (b) a :class:`TIN` /
:class:`Surface` / list of :class:`Contour` objects that *do* live in
memory but reference numpy arrays, not Python-level point lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from meridian.domain.crs import CRS
    from meridian.domain.geometry import BBox3D


class Classification(int, Enum):
    """ASPRS LAS standard classifications (subset)."""

    NEVER_CLASSIFIED = 0
    UNCLASSIFIED = 1
    GROUND = 2
    LOW_VEGETATION = 3
    MEDIUM_VEGETATION = 4
    HIGH_VEGETATION = 5
    BUILDING = 6
    LOW_NOISE = 7
    WATER = 9
    RAIL = 10
    ROAD_SURFACE = 11
    OVERLAP = 12
    WIRE_GUARD = 13
    WIRE_CONDUCTOR = 14
    TRANSMISSION_TOWER = 15
    BRIDGE_DECK = 17
    HIGH_NOISE = 18


@dataclass(frozen=True, slots=True)
class PointCloudStats:
    """Summary statistics for a point cloud."""

    point_count: int
    bbox: BBox3D
    has_classification: bool
    has_color: bool
    has_intensity: bool
    has_returns: bool
    classification_histogram: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PointCloud:
    """A reference to a point cloud stored on disk.

    Attributes
    ----------
    path
        Absolute path to a LAS, LAZ, or COPC file.
    crs
        CRS of the points (the LAS header's reported CRS, validated against
        the file's WKT/VLR).
    stats
        Cached statistics. Populated lazily by adapters.
    name
        Human-readable name (defaults to the file stem).
    is_copc
        ``True`` if the file is a Cloud-Optimized Point Cloud (streamable).

    """

    path: Path
    crs: CRS
    stats: PointCloudStats | None = None
    name: str | None = None
    is_copc: bool = False

    def label(self) -> str:
        return self.name or self.path.stem


@dataclass(frozen=True, slots=True)
class TIN:
    """A triangulated irregular network (Delaunay triangulation of points).

    Stored as numpy arrays for efficiency; not iterable point-by-point.
    """

    vertices: np.ndarray     # shape (N, 3): x, y, z
    triangles: np.ndarray    # shape (M, 3) of vertex indices
    crs: CRS

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])


@dataclass(frozen=True, slots=True)
class Contour:
    """A single iso-elevation contour line.

    ``polylines`` is a tuple of polylines (a contour at one elevation can
    consist of multiple disjoint pieces). Each polyline is an ``(N, 2)``
    numpy array.
    """

    elevation: float
    polylines: tuple[np.ndarray, ...]
    crs: CRS


@dataclass(frozen=True, slots=True)
class Surface:
    """A generated surface: TIN + raster DEM + iso-contours.

    Pipelines that produce a Surface guarantee internal consistency between
    the TIN, the rasterized DEM, and the contour set (all derived from the
    same source cloud at the same time).
    """

    name: str
    crs: CRS
    tin: TIN
    contours: tuple[Contour, ...] = ()
    dem_path: Path | None = None        # GeoTIFF on disk if rasterized
