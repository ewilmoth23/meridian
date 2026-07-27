"""NMEA 0183 driver — sentence parsing for live GNSS streams or logs.

Reads ``$GPGGA``, ``$GPRMC``, and ``$GPGSA`` sentences and produces
:class:`RawObservation` records of kind ``GNSS_POSITION`` (one per
fix epoch). Used both for offline log replay and (via
``meridian.adapters.instruments.serial_streams`` in v0.4) live serial /
Bluetooth feeds.
"""

from __future__ import annotations

from pathlib import Path

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult


class NMEADriver(InstrumentDriver):
    name = "NMEA 0183"
    short_id = "nmea"
    extensions = ("nmea", "log")

    def can_read(self, path: Path) -> bool:
        try:
            with path.open("r", encoding="ascii", errors="ignore") as f:
                for line in f:
                    if line.startswith(("$GP", "$GN", "$GL", "$GA")):
                        return True
                    if line.strip() and not line.startswith("$"):
                        return False
        except OSError:
            return False
        return False

    def read(self, path: Path) -> InstrumentReadResult:
        try:
            import pynmea2
        except ImportError:  # pragma: no cover
            return InstrumentReadResult(
                setups=(),
                observations=(),
                warnings=(
                    "pynmea2 not installed — install meridian[field] to enable NMEA parsing.",
                ),
            )
        setup = Setup(id="NMEA-1", occupied_point="ROVER", instrument_height=0.0)
        observations: list[RawObservation] = []
        with path.open("r", encoding="ascii", errors="ignore") as f:
            for lineno, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line.startswith("$"):
                    continue
                try:
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    continue
                if msg.sentence_type != "GGA":
                    continue
                if msg.gps_qual in (0, None):
                    continue  # No fix.
                lat = float(msg.latitude)
                lon = float(msg.longitude)
                alt = float(msg.altitude or 0)
                observations.append(
                    RawObservation(
                        id=f"NMEA-{lineno:06d}",
                        setup_id=setup.id,
                        kind=ObservationKind.GNSS_POSITION,
                        from_point="ROVER",
                        to_point=None,
                        vector=(lon, lat, alt),     # WGS84 lon/lat/h ellip.
                        sigma=(0.5, 0.5, 1.0),
                    )
                )
        return InstrumentReadResult(setups=(setup,), observations=tuple(observations))
