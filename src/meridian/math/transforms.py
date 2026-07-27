"""CRS transformations.

Wraps :mod:`pyproj` so that:

* Every transformation is **explicit** about source and target CRS.
* The transformation chain (e.g. NAD27 → NAD83(2011) → WGS84(G2139)) is
  computed once and cached.
* Grid-shift files (NADCON, HARN, GEOID18) are looked up from a
  configurable directory (``data/reference_grids/`` by default), or from
  pyproj's bundled set if they're missing locally.

We never silently pass through untransformed coordinates. If pyproj cannot
build a transformation (e.g. because the requested grid file isn't
available), a :class:`TransformationError` is raised.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np
import pyproj
from pyproj import Transformer

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point2D, Point3D


class TransformationError(RuntimeError):
    """Raised when no valid transformation between two CRSs can be built."""


@functools.lru_cache(maxsize=64)
def _make_transformer(src_wkt_or_epsg: str, dst_wkt_or_epsg: str) -> Transformer:
    """Build a pyproj Transformer, cached. ``always_xy=True`` so we always
    pass and return ``(x, y)`` regardless of the CRS axis ordering.
    """
    try:
        return Transformer.from_crs(src_wkt_or_epsg, dst_wkt_or_epsg, always_xy=True)
    except pyproj.exceptions.CRSError as e:  # pragma: no cover - defensive
        raise TransformationError(
            f"pyproj could not build a transformer from {src_wkt_or_epsg!r} to {dst_wkt_or_epsg!r}: {e}"
        ) from e


def _crs_key(crs: CRS) -> str:
    """Stable cache key for a CRS — EPSG when available else WKT."""
    if crs.epsg is not None:
        return f"EPSG:{crs.epsg}"
    if crs.wkt is not None:
        return crs.wkt
    raise ValueError("CRS has neither EPSG nor WKT.")  # pragma: no cover


def transform_xy(
    xs: np.ndarray,
    ys: np.ndarray,
    src: CRS,
    dst: CRS,
) -> tuple[np.ndarray, np.ndarray]:
    """Transform horizontal coordinates between two CRSs.

    Inputs and outputs are ``(N,)`` numpy arrays. Vectorised by pyproj.
    """
    if src == dst:
        return xs, ys
    transformer = _make_transformer(_crs_key(src), _crs_key(dst))
    out_x, out_y = transformer.transform(xs, ys)
    return np.asarray(out_x, dtype=np.float64), np.asarray(out_y, dtype=np.float64)


def transform_xyz(
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    src: CRS,
    dst: CRS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Transform 3D coordinates between two CRSs (handles geoid if defined)."""
    if src == dst:
        return xs, ys, zs
    transformer = _make_transformer(_crs_key(src), _crs_key(dst))
    out_x, out_y, out_z = transformer.transform(xs, ys, zs)
    return (
        np.asarray(out_x, dtype=np.float64),
        np.asarray(out_y, dtype=np.float64),
        np.asarray(out_z, dtype=np.float64),
    )


def transform_point2d(p: Point2D, dst: CRS) -> Point2D:
    """Transform a single :class:`Point2D` to a new CRS."""
    from meridian.domain.geometry import Point2D

    xs, ys = transform_xy(np.array([p.x]), np.array([p.y]), p.crs, dst)
    return Point2D(x=float(xs[0]), y=float(ys[0]), crs=dst, name=p.name, description=p.description)


def transform_point3d(p: Point3D, dst: CRS) -> Point3D:
    """Transform a single :class:`Point3D` to a new CRS."""
    from meridian.domain.geometry import Point3D

    xs, ys, zs = transform_xyz(
        np.array([p.x]), np.array([p.y]), np.array([p.z]), p.crs, dst
    )
    return Point3D(x=float(xs[0]), y=float(ys[0]), z=float(zs[0]), crs=dst, name=p.name, description=p.description)


def transform_points(
    points: Iterable[Point3D],
    dst: CRS,
) -> list[Point3D]:
    """Bulk-transform a list of :class:`Point3D`. All inputs must share a CRS."""
    pts = list(points)
    if not pts:
        return []
    src = pts[0].crs
    if any(p.crs != src for p in pts):
        raise ValueError("All input points must share a CRS.")
    xs = np.fromiter((p.x for p in pts), dtype=np.float64, count=len(pts))
    ys = np.fromiter((p.y for p in pts), dtype=np.float64, count=len(pts))
    zs = np.fromiter((p.z for p in pts), dtype=np.float64, count=len(pts))
    out_x, out_y, out_z = transform_xyz(xs, ys, zs, src, dst)
    from meridian.domain.geometry import Point3D

    return [
        Point3D(
            x=float(ox),
            y=float(oy),
            z=float(oz),
            crs=dst,
            name=p.name,
            description=p.description,
        )
        for p, ox, oy, oz in zip(pts, out_x, out_y, out_z)
    ]


def list_grid_files(directory: str | None = None) -> list[str]:
    """List grid-shift files known to pyproj at ``directory``.

    Used by setup wizards to verify that NADCON5/GEOID18 grids are present.
    """
    from pathlib import Path

    base = Path(directory) if directory else Path(pyproj.datadir.get_data_dir())
    return [str(p) for p in base.rglob("*.tif")]
