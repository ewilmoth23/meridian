"""Port: instrument driver.

An instrument driver knows how to read a single raw-data format produced
by a survey instrument (Leica GSI, Trimble JXL, Sokkia SDR, TDS RW5,
Nikon RAW, generic RINEX, NMEA streams).

Responsibilities:
* Inspect a file path or byte stream and decide whether it can read it.
* Parse it into :class:`~meridian.domain.observation.RawObservation` and
  :class:`~meridian.domain.observation.Setup` records.
* Optionally produce a list of inferred :class:`Point3D` for any explicit
  coordinate records the file carries.

Out of scope:
* No COGO. No closure check. No CRS transform. Just translate the file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.geometry import Point3D
    from meridian.domain.observation import RawObservation, Setup


@dataclass(frozen=True, slots=True)
class InstrumentReadResult:
    """The output of running an instrument driver."""

    setups: tuple[Setup, ...]
    observations: tuple[RawObservation, ...]
    coordinates: tuple[Point3D, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class InstrumentDriver(ABC):
    """Abstract base class for instrument drivers.

    Concrete drivers are registered as entry points under
    ``meridian.instruments`` and discovered at startup by
    :mod:`meridian.plugins`.
    """

    #: Display name shown in the UI ("Leica GSI-8/16").
    name: str = ""

    #: Short identifier used in CLI / config ("leica_gsi").
    short_id: str = ""

    #: File extensions handled (lowercase, without dot).
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def can_read(self, path: Path) -> bool:
        """Quick sniff: does this driver recognise the file?

        Should be fast — typically extension match + a few bytes of magic
        / first-line inspection.
        """

    @abstractmethod
    def read(self, path: Path) -> InstrumentReadResult:
        """Parse the file and return setups + observations + coordinates."""
