"""Abstract interfaces (ports) for adapters to implement.

These are the *shape* of every external integration: a database, a CAD
file format, a total-station data file, an LLM provider. Adapters live
in :mod:`meridian.adapters` and implement the corresponding port.

Hard rule: services in :mod:`meridian.services` and pipelines in
:mod:`meridian.pipelines` depend on ports, never on concrete adapters.
The plugin / DI machinery in :mod:`meridian.plugins` resolves the
implementation at runtime.
"""

from __future__ import annotations

from meridian.ports.exporter import Exporter, ExportResult
from meridian.ports.importer import Importer, ImportResult
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult
from meridian.ports.repository import (
    DeedRepository,
    ParcelRepository,
    PointCloudRepository,
    SurveyRepository,
)

__all__ = [
    "DeedRepository",
    "ExportResult",
    "Exporter",
    "ImportResult",
    "Importer",
    "InstrumentDriver",
    "InstrumentReadResult",
    "ParcelRepository",
    "PointCloudRepository",
    "SurveyRepository",
]
