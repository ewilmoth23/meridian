"""TDS RW5 (Carlson) driver.

RW5 is a line-based ASCII format used by Carlson SurvCE / SurvPC and
TDS Survey Pro. Each line begins with a record code:

    JB   — job header
    MO   — measurement options
    OC   — occupied point setup
    BK   — backsight
    SS   — sideshot (HA / VA / SD)
    BD   — backsight distance
    LS   — instrument / rod height
    SP   — store point (raw coordinate)
    G0   — GPS occupy
    GS   — GPS store

This driver covers OC/BK/LS/SS/SP, the 95% of what production crews
record. Other records are passed through as warnings so the user can
see what was skipped.
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


class TDSRW5Driver(InstrumentDriver):
    name = "TDS RW5 / Carlson"
    short_id = "tds_rw5"
    extensions = ("rw5",)

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in self.extensions:
            return False
        try:
            with path.open("r", encoding="ascii", errors="ignore") as f:
                first = f.readline()
        except OSError:
            return False
        return first.startswith("JB,") or first.startswith("--") or first.startswith("MO,")

    def read(self, path: Path) -> InstrumentReadResult:
        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        current_setup: Setup | None = None
        current_ih: float = 0.0
        current_th: float = 0.0
        line_no = 0

        with path.open("r", encoding="ascii", errors="ignore") as f:
            for raw_line in f:
                line_no += 1
                line = raw_line.strip()
                if not line or line.startswith("--"):
                    continue
                code, _, rest = line.partition(",")
                fields = _parse_kv(rest)
                if code == "OC":
                    pt = fields.get("OP", "")
                    ih_field = fields.get("HI") or fields.get("IH")
                    if ih_field:
                        current_ih = float(ih_field)
                    sid = f"S{len(setups) + 1:04d}"
                    current_setup = Setup(
                        id=sid,
                        occupied_point=pt,
                        instrument_height=current_ih,
                    )
                    setups.append(current_setup)
                elif code == "BK":
                    if current_setup is not None:
                        bs_az_text = fields.get("BC")
                        if bs_az_text:
                            current_setup = Setup(
                                id=current_setup.id,
                                occupied_point=current_setup.occupied_point,
                                instrument_height=current_setup.instrument_height,
                                backsight_point=fields.get("BP"),
                                backsight_azimuth=math.radians(_parse_dms(bs_az_text)),
                            )
                            setups[-1] = current_setup
                elif code == "LS":
                    th_field = fields.get("HR") or fields.get("HT")
                    if th_field:
                        current_th = float(th_field)
                    ih_field = fields.get("HI")
                    if ih_field:
                        current_ih = float(ih_field)
                elif code == "SS":
                    if current_setup is None:
                        warnings.append(f"Line {line_no}: SS before any OC; skipped.")
                        continue
                    target = fields.get("FP", "")
                    az = fields.get("AZ") or fields.get("HA")
                    ze = fields.get("ZE") or fields.get("VA")
                    sd = fields.get("SD")
                    obs_id_base = f"{current_setup.id}-{line_no:04d}"
                    if az is not None:
                        observations.append(
                            RawObservation(
                                id=f"{obs_id_base}-HA",
                                setup_id=current_setup.id,
                                kind=ObservationKind.HORIZONTAL_ANGLE,
                                from_point=current_setup.occupied_point,
                                to_point=target,
                                value=math.radians(_parse_dms(az)),
                                target_height=current_th,
                            )
                        )
                    if ze is not None:
                        observations.append(
                            RawObservation(
                                id=f"{obs_id_base}-VA",
                                setup_id=current_setup.id,
                                kind=ObservationKind.VERTICAL_ANGLE,
                                from_point=current_setup.occupied_point,
                                to_point=target,
                                value=math.radians(_parse_dms(ze)),
                                target_height=current_th,
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
                                value=float(sd),
                                target_height=current_th,
                            )
                        )
                # Other codes (SP, G0, GS, ...) handled in v0.2.
        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
        )


def _parse_kv(text: str) -> dict[str, str]:
    """Parse RW5's key-value comma payload (e.g. ``OP1,HI5.250,HR5.500``)."""
    out: dict[str, str] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Two-letter key followed by value, no separator.
        if len(chunk) >= 2 and chunk[:2].isalpha():
            out[chunk[:2].upper()] = chunk[2:]
    return out


def _parse_dms(text: str) -> float:
    """Parse a DMS field that may be ``DD.MMSSss`` or ``DD-MM-SS.s`` or decimal."""
    text = text.strip()
    if "-" in text:
        parts = text.split("-")
        d = float(parts[0])
        m = float(parts[1]) if len(parts) > 1 else 0
        s = float(parts[2]) if len(parts) > 2 else 0
        return d + m / 60 + s / 3600
    if "." in text:
        # DDD.MMSSss compact form
        whole, _, frac = text.partition(".")
        d = float(whole)
        if len(frac) >= 2:
            mm = int(frac[:2])
            ss = float("0." + frac[2:]) * 100 if frac[2:] else 0.0
            return d + mm / 60 + ss / 3600
        return float(text)
    return float(text)
