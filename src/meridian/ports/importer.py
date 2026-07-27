"""Port: importer.

An importer takes a file (DXF, LandXML, Shapefile, GeoPackage, GeoJSON,
KML, LAS) and parses it into domain entities (parcels, point clouds,
control networks).

Importers and :class:`~meridian.ports.instrument.InstrumentDriver` are
deliberately separate ports: instrument drivers handle *raw observations*
from field instruments; importers handle *processed deliverables* from
other software.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.parcel import Parcel
    from meridian.domain.pointcloud import PointCloud


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Result of an import."""

    parcels: tuple[Parcel, ...] = ()
    point_clouds: tuple[PointCloud, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class Importer(ABC):
    """Abstract base class for importers."""

    name: str = ""
    short_id: str = ""
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def can_read(self, path: Path) -> bool:
        ...

    @abstractmethod
    def read(self, path: Path, **options: object) -> ImportResult:
        ...
