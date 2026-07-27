"""Port: exporter.

An exporter takes a :class:`~meridian.domain.survey.Survey` (or a single
:class:`~meridian.domain.parcel.Parcel`, depending on the format) and
writes it out as a file in a particular format: DXF, LandXML, Shapefile,
GeoPackage, GeoJSON, KML, LAS, PDF report.

Out of scope:
* No coordinate transformation. The caller must hand us a Survey already
  in the target CRS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.parcel import Parcel
    from meridian.domain.survey import Survey


class ExportTarget(str, Enum):
    """What the exporter accepts as input."""

    SURVEY = "survey"
    PARCEL = "parcel"
    POINT_CLOUD = "point_cloud"
    NETWORK_ADJUSTMENT = "network_adjustment"


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Result of an export."""

    output_path: Path
    bytes_written: int
    warnings: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class Exporter(ABC):
    """Abstract base class for exporters."""

    name: str = ""
    short_id: str = ""
    extensions: tuple[str, ...] = ()
    target: ExportTarget = ExportTarget.SURVEY

    @abstractmethod
    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        """Write ``survey`` to ``output_path``.

        ``options`` is exporter-specific and is passed through from the
        service layer / CLI / GUI.
        """

    def export_parcel(self, parcel: Parcel, output_path: Path, **options: object) -> ExportResult:
        """Default fallback: wrap the parcel in a single-parcel survey and
        delegate to :meth:`export_survey`. Exporters with a more direct
        path can override.
        """
        from meridian.domain.survey import Survey

        survey = Survey(name=parcel.name, crs=parcel.crs)
        survey.parcels.append(parcel)
        return self.export_survey(survey, output_path, **options)
