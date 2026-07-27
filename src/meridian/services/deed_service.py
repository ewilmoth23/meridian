"""Deed service — orchestrates deed parsing → DXF/PDF outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.adapters.cad.dxf_writer import DXFExporter
from meridian.adapters.reports.pdf_writer import PDFReportExporter
from meridian.domain.geometry import Point2D
from meridian.domain.parcel import Parcel, ParcelMetadata
from meridian.domain.survey import Survey, SurveyProject
from meridian.pipelines.deed_to_polygon import (
    boundary_from_calls,
    parse_deed_text,
)

if TYPE_CHECKING:
    from meridian.domain.crs import CRS


@dataclass(frozen=True, slots=True)
class DeedToCADResult:
    project: SurveyProject
    parcel: Parcel
    dxf_path: Path | None
    pdf_path: Path | None
    misclosure_m: float
    closure_ratio: float


class DeedService:
    """Top-level deed-handling use-cases."""

    def parse_to_cad(
        self,
        *,
        text: str,
        crs: CRS,
        starting_point: tuple[float, float] = (0.0, 0.0),
        parcel_name: str = "Parcel A",
        dxf_path: Path | None = None,
        pdf_path: Path | None = None,
        surveyor: str | None = None,
        client: str | None = None,
    ) -> DeedToCADResult:
        """End-to-end: deed text → parcel → DXF + PDF."""
        parsed = parse_deed_text(text)
        pob = Point2D(x=starting_point[0], y=starting_point[1], crs=crs, name="POB")
        boundary = boundary_from_calls(parsed.calls, pob)
        metadata = ParcelMetadata(legal_description_text=text)
        parcel = Parcel(name=parcel_name, crs=crs, calls=parsed.calls, boundary=boundary, metadata=metadata)

        survey = Survey(name=parcel_name, crs=crs)
        survey.parcels.append(parcel)
        project = SurveyProject(name=parcel_name)
        project.add_survey(survey)

        if dxf_path is not None:
            DXFExporter().export_survey(survey, dxf_path)
        if pdf_path is not None:
            PDFReportExporter().export_survey(
                survey, pdf_path, surveyor=surveyor or "", client=client or ""
            )
        return DeedToCADResult(
            project=project,
            parcel=parcel,
            dxf_path=dxf_path,
            pdf_path=pdf_path,
            misclosure_m=boundary.misclosure_distance,
            closure_ratio=boundary.closure_ratio,
        )
