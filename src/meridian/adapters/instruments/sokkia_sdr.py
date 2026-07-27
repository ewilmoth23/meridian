"""Sokkia SDR2x / SDR33 reader.

The SDR series is record-oriented ASCII. Each line begins with a
two-digit record code. We implement the records that carry traverse
data (95% of production field files):

* ``00`` — header (file id, instrument, units flag).
* ``01`` — job identification.
* ``02`` — instrument constants (atmospheric correction, prism offset).
* ``03`` — coordinates (PNEZD record).
* ``07`` — target / rod height (a.k.a. HR).
* ``08`` — observation (HA, VA, SD).
* ``09`` — backsight definition.
* ``13`` — note / point coordinate store.

Other records (15 .. 99) are passed through as warnings.

Units flag (header column 40) controls angle and distance interpretation:
* ``1`` = metres + DMS
* ``2`` = US ft + DMS
* ``3`` = international ft + DMS
* ``4`` = metres + gons (gradians)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult

_DRIVER_VERSION = "0.2.0"


class SokkiaSDRDriver(InstrumentDriver):
    name = "Sokkia SDR2x / SDR33"
    short_id = "sokkia_sdr"
    extensions = ("sdr",)

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in self.extensions:
            return False
        try:
            with path.open("r", encoding="ascii", errors="ignore") as f:
                first = f.readline()
        except OSError:
            return False
        return first.startswith("00") or first.startswith("00NMSDR")

    def read(self, path: Path) -> InstrumentReadResult:
        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        units_factor = 1.0          # distances → metres
        angle_decoder = _decode_dms  # default DMS

        current_setup: Setup | None = None
        current_target_h = 0.0
        current_instr_h = 0.0

        with path.open("r", encoding="ascii", errors="ignore") as f:
            for lineno, raw_line in enumerate(f, start=1):
                line = raw_line.rstrip("\r\n")
                if len(line) < 2:
                    continue
                code = line[:2]
                rest = line[2:]
                if code == "00":
                    units_factor, angle_decoder, msg = _parse_header(rest)
                    if msg:
                        warnings.append(f"Line {lineno}: {msg}")
                elif code == "02":
                    # Instrument constants — we ignore for v0.2; flagged.
                    pass
                elif code == "03":
                    # PNEZD coordinate record — recorded but we don't use it
                    # in the traverse pipeline (it's a stored point, not an obs).
                    pass
                elif code == "07":
                    th = _parse_float(rest, units_factor)
                    if th is not None:
                        current_target_h = th
                elif code == "06":
                    # Instrument height (some Sokkia variants).
                    ih = _parse_float(rest, units_factor)
                    if ih is not None:
                        current_instr_h = ih
                elif code == "09":
                    # Backsight setup (PNT, BS_PNT, BS_AZ) — fields are
                    # space-separated in fixed-width form.
                    occ, bs_pt, bs_az = _parse_setup_fields(rest, units_factor, angle_decoder)
                    if occ is None:
                        warnings.append(f"Line {lineno}: malformed setup record; skipped.")
                        continue
                    current_setup = Setup(
                        id=f"S{len(setups) + 1:04d}",
                        occupied_point=occ,
                        instrument_height=current_instr_h,
                        backsight_point=bs_pt,
                        backsight_azimuth=bs_az,
                    )
                    setups.append(current_setup)
                elif code == "08":
                    if current_setup is None:
                        warnings.append(f"Line {lineno}: 08-observation before any 09-setup; skipped.")
                        continue
                    target, ha, va, sd = _parse_observation(rest, units_factor, angle_decoder)
                    if target is None:
                        warnings.append(f"Line {lineno}: malformed observation; skipped.")
                        continue
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
                                value=sd,
                                target_height=current_target_h,
                            )
                        )
                # codes 13/01/etc. ignored for v0.2.
        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
            metadata={"driver_version": _DRIVER_VERSION},
        )


# ── parsing helpers ────────────────────────────────────────────────────────


def _parse_header(rest: str) -> tuple[float, Callable[[str], float | None], str | None]:
    """Header record: returns (distance-to-metres factor, angle decoder, warning)."""
    # Sokkia headers have the units flag at column 40 of the line, but
    # different SDR versions place it differently. We accept either:
    # * char index 38 of the rest (matches SDR2x)
    # * a bare digit anywhere in the first 50 chars (lenient fallback)
    flag_chars = [c for c in rest[:50] if c.isdigit()]
    flag = flag_chars[-1] if flag_chars else "1"
    if flag == "1":
        return 1.0, _decode_dms, None
    if flag == "2":
        return 1200.0 / 3937.0, _decode_dms, None     # US survey ft
    if flag == "3":
        return 0.3048, _decode_dms, None              # international ft
    if flag == "4":
        return 1.0, _decode_gons, None
    return 1.0, _decode_dms, f"Unknown SDR units flag {flag!r}; defaulting to metres + DMS."


def _decode_dms(raw: str) -> float | None:
    """Decode a Sokkia DMS angle field of form ``DDDMMSSss`` into radians."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        # Float-form ``DDD.MMSSsss``
        if "." in raw:
            whole, _, frac = raw.partition(".")
            d = int(whole)
            mm = int(frac[:2]) if len(frac) >= 2 else 0
            ss = float("0." + frac[2:]) * 100 if frac[2:] else 0.0
            return math.radians(d + mm / 60 + ss / 3600)
        # Compact integer form
        n = int(raw)
        ss = (n % 100000) / 1000.0
        n //= 100000
        mm = n % 100
        d = n // 100
        return math.radians(d + mm / 60 + ss / 3600)
    except ValueError:
        return None


def _decode_gons(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return math.radians(float(raw) * 0.9)
    except ValueError:
        return None


def _parse_float(rest: str, units_factor: float) -> float | None:
    chunk = rest.strip().split()
    if not chunk:
        return None
    try:
        return float(chunk[0]) * units_factor
    except ValueError:
        return None


def _parse_setup_fields(rest: str, units_factor: float, angle_decoder) -> tuple[str | None, str | None, float | None]:
    parts = rest.strip().split()
    if not parts:
        return None, None, None
    occ = parts[0]
    bs_pt = parts[1] if len(parts) > 1 else None
    bs_az = angle_decoder(parts[2]) if len(parts) > 2 else None
    return occ, bs_pt, bs_az


def _parse_observation(
    rest: str, units_factor: float, angle_decoder
) -> tuple[str | None, float | None, float | None, float | None]:
    """Parse an 08 record's payload into (target, HA, VA, SD)."""
    parts = rest.strip().split()
    if not parts:
        return None, None, None, None
    target = parts[0]
    ha = angle_decoder(parts[1]) if len(parts) > 1 else None
    va = angle_decoder(parts[2]) if len(parts) > 2 else None
    sd = None
    if len(parts) > 3:
        try:
            sd = float(parts[3]) * units_factor
        except ValueError:
            sd = None
    return target, ha, va, sd
