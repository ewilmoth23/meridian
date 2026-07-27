"""PDAL-backed point-cloud pipelines.

PDAL is the reference engine for processing LAS/LAZ at scale. Every
operation is expressed as a JSON pipeline of ``readers → filters →
writers``. We keep the JSON authoring out of user code by exposing
named helpers — :func:`classify_ground`, :func:`filter_by_classification`,
:func:`thin_uniform`, :func:`compute_dem` — and let advanced users
provide their own JSON via :func:`run_pipeline_json`.

PDAL Python bindings are an optional dependency (``meridian[pointcloud]``).
When unavailable, this module raises a clear error so the desktop UI can
surface it instead of crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _require_pdal() -> Any:
    try:
        import pdal
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "PDAL Python bindings are not installed. Install with: "
            "pip install meridian[pointcloud] (and ensure system PDAL is present)."
        ) from e
    return pdal


def run_pipeline_json(spec: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    """Execute a PDAL pipeline JSON; return its summary metadata."""
    pdal = _require_pdal()
    if isinstance(spec, dict):
        json_str = json.dumps(spec)
    else:
        json_str = json.dumps({"pipeline": spec})
    pipeline = pdal.Pipeline(json_str)
    pipeline.execute()
    return {
        "metadata": pipeline.metadata,
        "log": pipeline.log,
    }


def classify_ground(
    input_path: Path,
    output_path: Path,
    *,
    method: str = "smrf",
    cell: float = 1.0,
    slope: float = 0.15,
    threshold: float = 0.5,
    window: float = 18.0,
) -> dict[str, Any]:
    """Run ground classification on a LAS/LAZ file.

    Methods:
    * ``"smrf"`` — Simple Morphological Filter (default; good general-purpose).
    * ``"pmf"`` — Progressive Morphological Filter (older, faster, less robust).

    Output is a new LAS/LAZ file with ASPRS class 2 (ground) populated.
    Other point classes are preserved.

    """
    if method.lower() == "smrf":
        filter_stage: dict[str, Any] = {
            "type": "filters.smrf",
            "cell": cell,
            "slope": slope,
            "threshold": threshold,
            "window": window,
        }
    elif method.lower() == "pmf":
        filter_stage = {"type": "filters.pmf"}
    else:
        raise ValueError(f"Unknown ground-classification method: {method!r}")

    pipeline = [
        {"type": "readers.las", "filename": str(input_path)},
        filter_stage,
        {"type": "writers.las", "filename": str(output_path), "compression": "laszip"},
    ]
    return run_pipeline_json(pipeline)


def filter_by_classification(
    input_path: Path,
    output_path: Path,
    keep: tuple[int, ...] = (2,),
) -> dict[str, Any]:
    """Keep only the specified ASPRS classifications."""
    cls = ",".join(str(c) for c in keep)
    pipeline = [
        {"type": "readers.las", "filename": str(input_path)},
        {"type": "filters.range", "limits": f"Classification[{cls}:{cls}]" if len(keep) == 1 else "Classification![0:0]"},
        {"type": "filters.range", "limits": _make_class_limits(keep)},
        {"type": "writers.las", "filename": str(output_path), "compression": "laszip"},
    ]
    return run_pipeline_json(pipeline)


def _make_class_limits(keep: tuple[int, ...]) -> str:
    parts = [f"Classification[{c}:{c}]" for c in keep]
    return ",".join(parts)


def thin_uniform(input_path: Path, output_path: Path, spacing: float) -> dict[str, Any]:
    """Voxel-grid thin a cloud to uniform spacing."""
    pipeline = [
        {"type": "readers.las", "filename": str(input_path)},
        {"type": "filters.voxelcenternearestneighbor", "cell": spacing},
        {"type": "writers.las", "filename": str(output_path), "compression": "laszip"},
    ]
    return run_pipeline_json(pipeline)


def compute_dem(
    input_path: Path,
    output_path: Path,
    *,
    resolution: float = 1.0,
    classifications: tuple[int, ...] = (2,),
) -> dict[str, Any]:
    """Generate a DEM GeoTIFF from ground-classified points."""
    pipeline = [
        {"type": "readers.las", "filename": str(input_path)},
        {"type": "filters.range", "limits": _make_class_limits(classifications)},
        {
            "type": "writers.gdal",
            "filename": str(output_path),
            "resolution": resolution,
            "output_type": "idw",
            "data_type": "float32",
        },
    ]
    return run_pipeline_json(pipeline)
