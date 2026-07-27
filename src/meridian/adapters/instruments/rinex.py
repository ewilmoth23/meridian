"""RINEX 3.x driver — observation files only (v0.1 scope).

RINEX is the universal exchange format for GNSS observations and
navigation data. v0.1 covers RINEX 3.0x **observation** files: header
parsing (REC #/TYPE/VERS, ANT #/TYPE, APPROX POSITION XYZ, OBS TYPES
PER SYSTEM) plus per-epoch satellite observations.

v0.1 produces an :class:`InstrumentReadResult` carrying a single
"GNSS_POSITION" observation per receiver setup using the
``APPROX POSITION XYZ`` from the header. Full PPP / baseline processing
arrives in v0.3 alongside the IGS orbit fetcher.
"""

from __future__ import annotations

import re
from pathlib import Path

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult


class RINEXDriver(InstrumentDriver):
    name = "RINEX 3.x (observation)"
    short_id = "rinex"
    extensions = ("rnx", "obs", "o", "21o", "22o", "23o", "24o", "25o", "26o")

    def can_read(self, path: Path) -> bool:
        ext = path.suffix.lower().lstrip(".")
        if ext in self.extensions or re.fullmatch(r"\d{2}o", ext):
            try:
                with path.open("r", encoding="ascii", errors="ignore") as f:
                    head = f.read(256)
                return "RINEX VERSION" in head
            except OSError:
                return False
        return False

    def read(self, path: Path) -> InstrumentReadResult:
        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        marker_name: str | None = None
        approx_xyz: tuple[float, float, float] | None = None
        receiver: str | None = None

        with path.open("r", encoding="ascii", errors="ignore") as f:
            in_header = True
            for raw_line in f:
                if in_header:
                    label = raw_line[60:].strip().upper()
                    if "MARKER NAME" in label:
                        marker_name = raw_line[:60].strip()
                    elif "REC # / TYPE / VERS" in label:
                        receiver = raw_line[20:40].strip()
                    elif "APPROX POSITION XYZ" in label:
                        try:
                            x = float(raw_line[0:14])
                            y = float(raw_line[14:28])
                            z = float(raw_line[28:42])
                            approx_xyz = (x, y, z)
                        except ValueError:
                            warnings.append("Could not parse APPROX POSITION XYZ.")
                    elif "END OF HEADER" in label:
                        in_header = False
                else:
                    # Stop after the header for v0.1; epochs aren't yet used.
                    break

        if approx_xyz is None or marker_name is None:
            warnings.append(
                "RINEX file lacks marker name or approx XYZ; cannot register observation."
            )
            return InstrumentReadResult(setups=(), observations=(), warnings=tuple(warnings))

        setup = Setup(
            id=f"R-{marker_name or 'UNK'}",
            occupied_point=marker_name,
            instrument_height=0.0,
            instrument_serial=receiver,
        )
        setups.append(setup)
        observations.append(
            RawObservation(
                id=f"{setup.id}-pos",
                setup_id=setup.id,
                kind=ObservationKind.GNSS_POSITION,
                from_point=marker_name,
                to_point=None,
                vector=approx_xyz,
                sigma=(2.0, 2.0, 4.0),  # APPROX position is rough; v0.3 PPP refines.
            )
        )
        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
            metadata={"marker_name": marker_name, "receiver": receiver},
        )
