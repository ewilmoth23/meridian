"""Nikon RAW reader.

Nikon-style ``.raw`` files (also written by older Topcon GTS) are
record-oriented ASCII with a one- or two-letter record type followed by
comma-separated fields. The records we care about for traversing:

    ST,<station_pt>,<bs_pt>,<ih>,<bs_az_dms>,<note>
    HV,<target>,<ha_dms>,<va_dms>,<sd_m>,<th>
    SS,<target>,<ha_dms>,<va_dms>,<sd_m>,<th>,<code>
    PT,<pt>,<n>,<e>,<elev>,<code>
    JE,<job_id>,<units_flag>,<date>

Units flag (``1``=metres, ``2``=US ft, ``3``=international ft).
"""

from __future__ import annotations

import math
from pathlib import Path

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult

_DRIVER_VERSION = "0.2.0"


class NikonRawDriver(InstrumentDriver):
    name = "Nikon RAW (Topcon-compatible)"
    short_id = "nikon_raw"
    extensions = ("raw",)

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in self.extensions:
            return False
        try:
            with path.open("r", encoding="ascii", errors="ignore") as f:
                first = f.readline().strip()
        except OSError:
            return False
        return first.startswith(("ST,", "JE,", "HV,", "SS,", "PT,"))

    def read(self, path: Path) -> InstrumentReadResult:
        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        units_factor = 1.0
        current_setup: Setup | None = None
        current_target_h = 0.0

        with path.open("r", encoding="ascii", errors="ignore") as f:
            for lineno, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line or line.startswith("--"):
                    continue
                fields = line.split(",")
                code = fields[0].strip().upper()
                if code == "JE":
                    if len(fields) > 2:
                        flag = fields[2].strip()
                        if flag == "2":
                            units_factor = 1200.0 / 3937.0
                        elif flag == "3":
                            units_factor = 0.3048
                        else:
                            units_factor = 1.0
                elif code == "ST":
                    occ = fields[1].strip() if len(fields) > 1 else ""
                    bs_pt = fields[2].strip() if len(fields) > 2 else None
                    ih = _safe_float(fields[3]) if len(fields) > 3 else 0.0
                    bs_az = _decode_dms(fields[4]) if len(fields) > 4 else None
                    sid = f"S{len(setups) + 1:04d}"
                    current_setup = Setup(
                        id=sid,
                        occupied_point=occ,
                        instrument_height=(ih or 0.0) * units_factor,
                        backsight_point=bs_pt,
                        backsight_azimuth=bs_az,
                    )
                    setups.append(current_setup)
                elif code in ("SS", "HV"):
                    if current_setup is None:
                        warnings.append(f"Line {lineno}: {code} before any ST; skipped.")
                        continue
                    target = fields[1].strip() if len(fields) > 1 else ""
                    ha = _decode_dms(fields[2]) if len(fields) > 2 else None
                    va = _decode_dms(fields[3]) if len(fields) > 3 else None
                    sd = _safe_float(fields[4]) if len(fields) > 4 else None
                    th = _safe_float(fields[5]) if len(fields) > 5 else current_target_h
                    if th is not None:
                        current_target_h = th * units_factor
                    obs_id_base = f"{current_setup.id}-{lineno:04d}"
                    if ha is not None:
                        observations.append(
                            RawObservation(
                                id=f"{obs_id_base}-HA",
                                setup_id=current_setup.id,
                                kind=ObservationKind.HORIZONTAL_ANGLE,
                                from_point=current_setup.occupied_point,
                                to_point=target,
                                value=ha,
                                target_height=current_target_h,
                            )
                        )
                    if va is not None:
                        observations.append(
                            RawObservation(
                                id=f"{obs_id_base}-VA",
                                setup_id=current_setup.id,
                                kind=ObservationKind.VERTICAL_ANGLE,
                                from_point=current_setup.occupied_point,
                                to_point=target,
                                value=va,
                                target_height=current_target_h,
                            )
                        )
                    if sd is not None:
                        observations.append(
                            RawObservation(
                                id=f"{obs_id_base}-SD",
                                setup_id=current_setup.id,
                                kind=ObservationKind.SLOPE_DISTANCE,
                                from_point=current_setup.occupied_point,
                                to_point=target,
                                value=sd * units_factor,
                                target_height=current_target_h,
                            )
                        )
                # PT (stored coords) ignored for v0.2.
        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
            metadata={"driver_version": _DRIVER_VERSION},
        )


def _safe_float(text: str) -> float | None:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def _decode_dms(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        if "-" in raw:
            parts = raw.split("-")
            d = float(parts[0])
            m = float(parts[1]) if len(parts) > 1 else 0
            s = float(parts[2]) if len(parts) > 2 else 0
            return math.radians(d + m / 60 + s / 3600)
        if "." in raw:
            whole, _, frac = raw.partition(".")
            d = int(whole)
            mm = int(frac[:2]) if len(frac) >= 2 else 0
            ss = float("0." + frac[2:]) * 100 if frac[2:] else 0.0
            return math.radians(d + mm / 60 + ss / 3600)
        return math.radians(float(raw))
    except ValueError:
        return None
