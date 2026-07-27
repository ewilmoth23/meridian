"""Pipeline: LAS/LAZ → classified → ground TIN → contours.

Composes :mod:`meridian.adapters.pointcloud.pdal_pipeline` (for the
billion-point classification) with :mod:`meridian.adapters.pointcloud.las_io`
(for reading classified ground back into numpy) and
:mod:`meridian.math.triangulation` (for TIN + contouring).

Returns a :class:`~meridian.domain.pointcloud.Surface` referencing:
* a TIN built from classified ground points
* a tuple of :class:`Contour` objects at the requested elevations
* (optionally) a path to a rasterised DEM

The pipeline is split into three steps so the desktop UI can stream
progress updates between them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from meridian.adapters.pointcloud.las_io import LASImporter, read_classified_points
from meridian.adapters.pointcloud.pdal_pipeline import classify_ground, compute_dem
from meridian.domain.pointcloud import (
    TIN,
    Classification,
    Contour,
    PointCloud,
    Surface,
)
from meridian.math.triangulation import extract_contours, tin_from_points


@dataclass(slots=True)
class PointCloudPipelineOptions:
    """Tuning knobs for the full classify→TIN→contour pipeline."""

    contour_interval_m: float = 1.0
    contour_index_every: int = 5         # every Nth contour drawn at index weight
    smrf_cell: float = 1.0
    smrf_slope: float = 0.15
    smrf_threshold: float = 0.5
    smrf_window: float = 18.0
    target_thin_spacing_m: float | None = None    # None = no thinning
    generate_dem: bool = False
    dem_resolution_m: float = 1.0


def classify_and_load_ground(
    input_path: Path,
    *,
    options: PointCloudPipelineOptions | None = None,
    classified_path: Path | None = None,
) -> tuple[PointCloud, np.ndarray]:
    """Run ground classification and return both the classified cloud and
    its ground points as a numpy array.

    Parameters
    ----------
    input_path
        LAS or LAZ on disk.
    options
        Tuning for the SMRF filter.
    classified_path
        Where to write the classified output. If ``None``, a temp file
        next to the input is used.

    """
    options = options or PointCloudPipelineOptions()
    if classified_path is None:
        classified_path = input_path.with_name(input_path.stem + ".classified.laz")
    classify_ground(
        input_path,
        classified_path,
        cell=options.smrf_cell,
        slope=options.smrf_slope,
        threshold=options.smrf_threshold,
        window=options.smrf_window,
    )
    importer = LASImporter()
    result = importer.read(classified_path)
    if not result.point_clouds:
        raise RuntimeError(f"PDAL classify did not produce a readable LAS at {classified_path}")
    cloud = result.point_clouds[0]
    ground_xyz = read_classified_points(cloud, classifications=(Classification.GROUND,))
    if ground_xyz.shape[0] < 3:
        raise RuntimeError(
            f"Only {ground_xyz.shape[0]} ground points after classification — adjust SMRF parameters."
        )
    return cloud, ground_xyz


def make_surface(
    cloud: PointCloud,
    ground_xyz: np.ndarray,
    *,
    options: PointCloudPipelineOptions | None = None,
    name: str | None = None,
    dem_path: Path | None = None,
) -> Surface:
    """Triangulate ground points and extract contours.

    For ground sets larger than 2M points, callers should thin first
    (PDAL ``thin_uniform``) — :func:`scipy.spatial.Delaunay` handles
    millions but you'll spend most of your wall time in the triangulation.
    """
    options = options or PointCloudPipelineOptions()
    vertices, triangles = tin_from_points(ground_xyz)

    z_min = float(vertices[:, 2].min())
    z_max = float(vertices[:, 2].max())
    interval = options.contour_interval_m
    if interval <= 0:
        raise ValueError("contour interval must be positive.")
    first = math.ceil(z_min / interval) * interval
    last = math.floor(z_max / interval) * interval
    elev_array = np.arange(first, last + interval / 2, interval, dtype=np.float64)

    contour_dict = extract_contours(vertices, triangles, elev_array)
    contours: list[Contour] = []
    for elev, polylines in contour_dict.items():
        if not polylines:
            continue
        contours.append(
            Contour(
                elevation=elev,
                polylines=tuple(polylines),
                crs=cloud.crs,
            )
        )

    if options.generate_dem and dem_path is None:
        dem_path = cloud.path.with_suffix(".dem.tif")
    if options.generate_dem and dem_path is not None:
        compute_dem(cloud.path, dem_path, resolution=options.dem_resolution_m)

    return Surface(
        name=name or cloud.label(),
        crs=cloud.crs,
        tin=TIN(vertices=vertices, triangles=triangles, crs=cloud.crs),
        contours=tuple(contours),
        dem_path=dem_path,
    )
