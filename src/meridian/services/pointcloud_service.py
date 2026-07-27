"""Point-cloud service — LAS/LAZ → classified → TIN → contours → DXF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.adapters.cad.contour_dxf import write_surface_dxf
from meridian.domain.pointcloud import PointCloud, Surface
from meridian.pipelines.pointcloud_classify import (
    PointCloudPipelineOptions,
    classify_and_load_ground,
    make_surface,
)


@dataclass(frozen=True, slots=True)
class PointCloudRunResult:
    cloud: PointCloud
    classified_path: Path
    ground_point_count: int
    surface: Surface
    contour_dxf_path: Path | None
    dem_path: Path | None


class PointCloudService:
    """High-level orchestration for the cloud pipeline."""

    def classify_to_contours(
        self,
        input_path: Path,
        *,
        contour_dxf_path: Path | None = None,
        classified_path: Path | None = None,
        options: PointCloudPipelineOptions | None = None,
    ) -> PointCloudRunResult:
        opts = options or PointCloudPipelineOptions()
        cloud, ground_xyz = classify_and_load_ground(
            input_path, options=opts, classified_path=classified_path
        )
        surface = make_surface(cloud, ground_xyz, options=opts)
        if contour_dxf_path is not None:
            write_surface_dxf(
                surface,
                contour_dxf_path,
                index_every=opts.contour_index_every,
                interval_m=opts.contour_interval_m,
            )
        return PointCloudRunResult(
            cloud=cloud,
            classified_path=cloud.path,
            ground_point_count=int(ground_xyz.shape[0]),
            surface=surface,
            contour_dxf_path=contour_dxf_path,
            dem_path=surface.dem_path,
        )
