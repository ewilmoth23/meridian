"""LAS / LAZ adapter — built on :mod:`laspy`.

Reads / writes the ASPRS LAS standard (1.0 through 1.4) and its
LZ4-compressed sibling LAZ. ``laspy`` ships with optional LAZ support via
the ``lazrs`` Rust backend (recommended) or ``laszip``. Install with:

    pip install "laspy[lazrs]"

This adapter does **not** load the entire point set into Python memory.
For files larger than a few hundred MB the caller should pass through
the PDAL pipeline (:mod:`meridian.adapters.pointcloud.pdal_pipeline`)
which streams blocks of points without ever materialising them.

Responsibilities here:
* Open a LAS / LAZ file, parse its header, and produce a
  :class:`~meridian.domain.pointcloud.PointCloud` *reference*.
* Compute :class:`~meridian.domain.pointcloud.PointCloudStats` with one
  scan — point count, bbox, classification histogram.
* Read ``ground``-only points into a numpy array for surfacing.
* Write a LAS file from a numpy array (used by classification pipelines).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from meridian.domain.pointcloud import (
    Classification,
    PointCloud,
    PointCloudStats,
)
from meridian.ports.exporter import Exporter, ExportResult, ExportTarget
from meridian.ports.importer import Importer, ImportResult

if TYPE_CHECKING:
    from meridian.domain.crs import CRS


class LASImporter(Importer):
    """Importer for LAS / LAZ files producing a :class:`PointCloud`."""

    name = "LAS / LAZ"
    short_id = "las"
    extensions = ("las", "laz", "copc.laz", "copc")

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in {"las", "laz"} or str(path).lower().endswith(".copc.laz")

    def read(self, path: Path, **options: object) -> ImportResult:
        try:
            import laspy
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "LASImporter requires laspy. Install with: pip install 'laspy[lazrs]'"
            ) from e

        # Read header only (no point materialisation) for stats.
        with laspy.open(str(path)) as f:
            header = f.header
            point_count = int(header.point_count)
            min_xyz = (float(header.mins[0]), float(header.mins[1]), float(header.mins[2]))
            max_xyz = (float(header.maxs[0]), float(header.maxs[1]), float(header.maxs[2]))
            wkt = header.parse_crs().to_wkt() if header.parse_crs() else None

            # Classification histogram via streamed read (small buffer per chunk).
            histogram: Counter[int] = Counter()
            has_color = bool(header.point_format.has_color)
            for chunk in f.chunk_iterator(1_000_000):
                histogram.update(chunk.classification)

        from meridian.domain.geometry import BBox3D

        crs = options.get("crs") or _guess_crs_from_wkt(wkt)
        if crs is None:
            raise ValueError(
                f"LAS file {path} has no embedded CRS. Pass crs=... to read()."
            )
        bbox = BBox3D(
            min_x=min_xyz[0], min_y=min_xyz[1], min_z=min_xyz[2],
            max_x=max_xyz[0], max_y=max_xyz[1], max_z=max_xyz[2],
            crs=crs,
        )
        stats = PointCloudStats(
            point_count=point_count,
            bbox=bbox,
            has_classification=True,
            has_color=has_color,
            has_intensity=True,
            has_returns=True,
            classification_histogram={int(k): int(v) for k, v in histogram.items()},
        )
        is_copc = str(path).lower().endswith(".copc.laz") or _looks_like_copc(path)
        cloud = PointCloud(
            path=path.resolve(),
            crs=crs,
            stats=stats,
            name=path.stem,
            is_copc=is_copc,
        )
        return ImportResult(point_clouds=(cloud,))


def _guess_crs_from_wkt(wkt: str | None) -> CRS | None:
    if not wkt:
        return None
    from meridian.domain.crs import CRS
    return CRS(wkt=wkt)


def _looks_like_copc(path: Path) -> bool:
    """COPC files have a magic VLR — quick check on header."""
    try:
        with path.open("rb") as f:
            head = f.read(4096)
        return b"copc" in head.lower()
    except OSError:  # pragma: no cover
        return False


def read_classified_points(
    cloud: PointCloud,
    classifications: tuple[int, ...] = (Classification.GROUND,),
) -> np.ndarray:
    """Read only points with the requested classifications.

    Returns ``(N, 3)`` array of XYZ. Streams the file; suitable for
    multi-million-point datasets.
    """
    try:
        import laspy
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("laspy is required") from e
    selected = []
    cls_set = {int(c) for c in classifications}
    with laspy.open(str(cloud.path)) as f:
        for chunk in f.chunk_iterator(1_000_000):
            mask = np.isin(chunk.classification, list(cls_set))
            if not mask.any():
                continue
            xs = np.asarray(chunk.x[mask], dtype=np.float64)
            ys = np.asarray(chunk.y[mask], dtype=np.float64)
            zs = np.asarray(chunk.z[mask], dtype=np.float64)
            selected.append(np.column_stack([xs, ys, zs]))
    if not selected:
        return np.empty((0, 3), dtype=np.float64)
    return np.vstack(selected)


class LASExporter(Exporter):
    """Write a numpy array out as LAS (used by classification outputs)."""

    name = "LAS / LAZ"
    short_id = "las"
    extensions = ("las", "laz")
    target = ExportTarget.POINT_CLOUD

    def export_survey(self, survey: object, output_path: Path, **options: object) -> ExportResult:
        raise NotImplementedError("LAS export takes a PointCloud, not a Survey directly. Use export_array().")

    def export_array(
        self,
        xyz: np.ndarray,
        output_path: Path,
        *,
        classifications: np.ndarray | None = None,
        crs_wkt: str | None = None,
    ) -> ExportResult:
        try:
            import laspy
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("laspy is required") from e
        if xyz.ndim != 2 or xyz.shape[1] != 3:
            raise ValueError(f"Expected (N, 3), got {xyz.shape}")
        header = laspy.LasHeader(point_format=6, version="1.4")
        if crs_wkt:
            header.add_crs(crs_wkt)
        las = laspy.LasData(header)
        las.x = xyz[:, 0]
        las.y = xyz[:, 1]
        las.z = xyz[:, 2]
        if classifications is not None:
            las.classification = classifications.astype(np.uint8)
        las.write(str(output_path))
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            metadata={"point_count": int(xyz.shape[0])},
        )
