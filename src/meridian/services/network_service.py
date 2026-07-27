"""Network service — orchestrates raw observations → adjustment → reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.adapters.reports.pdf_writer import PDFReportExporter
from meridian.domain.network import (
    ConstraintMode,
    ControlNetwork,
    ControlPoint,
    NetworkAdjustment,
)
from meridian.domain.observation import RawObservation
from meridian.domain.survey import Survey, SurveyProject
from meridian.pipelines.network_adjust import NetworkAdjustOptions, adjust
from meridian.plugins.discovery import get_registry

if TYPE_CHECKING:
    from meridian.domain.crs import CRS


@dataclass(frozen=True, slots=True)
class NetworkAdjustmentRunResult:
    project: SurveyProject
    adjustment: NetworkAdjustment
    pdf_path: Path | None


class NetworkService:
    """Use-cases for control-network adjustment."""

    def adjust_network(
        self,
        *,
        name: str,
        crs: CRS,
        points: list[ControlPoint],
        observations: list[RawObservation],
        constraint_mode: ConstraintMode = ConstraintMode.MINIMAL,
        options: NetworkAdjustOptions | None = None,
        pdf_path: Path | None = None,
    ) -> NetworkAdjustmentRunResult:
        net = ControlNetwork(
            name=name,
            crs=crs,
            points=tuple(points),
            observations=tuple(observations),
            constraint_mode=constraint_mode,
        )
        adj = adjust(net, options or NetworkAdjustOptions())

        survey = Survey(name=name, crs=crs)
        survey.networks.append(net)
        survey.adjustments.append(adj)
        project = SurveyProject(name=name)
        project.add_survey(survey)

        if pdf_path is not None:
            PDFReportExporter().export_survey(survey, pdf_path)

        return NetworkAdjustmentRunResult(project=project, adjustment=adj, pdf_path=pdf_path)

    def import_from_file(self, path: Path) -> tuple[list[ControlPoint], list[RawObservation], list[str]]:
        """Use a registered instrument driver to read setups + observations."""
        reg = get_registry()
        driver = reg.driver_for_path(path)
        if driver is None:
            raise ValueError(
                f"No registered instrument driver can read {path}. "
                f"Available: {sorted(reg.instruments)}"
            )
        result = driver.read(path)
        # Build placeholder ControlPoints from observation point names. The
        # caller provides a-priori coordinates separately; we return empty
        # by default so they can be merged in.
        return [], list(result.observations), list(result.warnings)
