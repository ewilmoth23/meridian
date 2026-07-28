"""Leica GSI driver (GSI-8 and GSI-16).

GSI is the line-based survey-data format used by Leica TPS, NA and DNA
instruments. Each line is a series of word IDs followed by 8-digit
(GSI-8) or 16-digit (GSI-16) values. Word IDs of interest:

    11   point number
    21   horizontal angle
    22   vertical angle
    31   horizontal distance
    32   slope distance
    33   height difference
    81   easting
    82   northing
    83   elevation
    84   instrument height
    85   target height
    87   reflector height
    88   prism constant

A word's last digit before the value is its scale-and-sign code, e.g.
``32..16+0000123456789012`` is a slope distance with three implied
decimals — i.e. ``123456.789012 m``. We honour the standard scales
(``..00``, ``..06``, ``..16`` for cm, mm, 0.1 mm).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.ports.instrument import InstrumentDriver, InstrumentReadResult

# Each Leica GSI word is `WI` + 2-char info + 2-char scale + sign + 8/16-digit value.
# The info and scale fields can each be digits or dots (".." = unspecified). We
# capture all four parts and let the parser decide how to interpret each.
_WORD_RE = re.compile(r"(\d{2})([\d.]{2})([\d.]{2})([+-])(\d{8,16})")


class LeicaGSIDriver(InstrumentDriver):
    """Reader for GSI-8 / GSI-16 files."""

    name = "Leica GSI-8/16"
    short_id = "leica_gsi"
    extensions = ("gsi", "gsi8", "gsi16")

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in self.extensions:
            return False
        try:
            with path.open("r", encoding="ascii", errors="ignore") as f:
                first = f.readline()
        except OSError:
            return False
        return bool(_WORD_RE.search(first))

    def read(self, path: Path) -> InstrumentReadResult:
        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        current_setup: Setup | None = None
        with path.open("r", encoding="ascii", errors="ignore") as f:
            for lineno, raw_line in enumerate(f, start=1):
                words = _parse_line(raw_line)
                if not words:
                    continue
                point = words.get(11)
                # A line with only "STN" / station setup info begins a setup.
                if 84 in words and 11 in words:
                    current_setup = Setup(
                        id=f"S{len(setups) + 1:04d}",
                        occupied_point=str(point),
                        instrument_height=words[84],
                    )
                    setups.append(current_setup)
                    continue
                if current_setup is None:
                    warnings.append(f"Line {lineno}: observation before any setup; skipped.")
                    continue
                # Build observations for whichever measurement words are present.
                from_pt = current_setup.occupied_point
                to_pt = str(point) if point is not None else None
                target_h = words.get(87) or words.get(85)
                obs_id_base = f"{current_setup.id}-{lineno:04d}"
                if 21 in words:
                    observations.append(
                        RawObservation(
                            id=f"{obs_id_base}-HA",
                            setup_id=current_setup.id,
                            kind=ObservationKind.HORIZONTAL_ANGLE,
                            from_point=from_pt,
                            to_point=to_pt,
                            value=math.radians(words[21]),
                            target_height=target_h,
                        )
                    )
                if 22 in words:
                    observations.append(
                        RawObservation(
                            id=f"{obs_id_base}-VA",
                            setup_id=current_setup.id,
                            kind=ObservationKind.VERTICAL_ANGLE,
                            from_point=from_pt,
                            to_point=to_pt,
                            value=math.radians(words[22]),
                            target_height=target_h,
                        )
                    )
                if 31 in words:
                    observations.append(
                        RawObservation(
                            id=f"{obs_id_base}-HD",
                            setup_id=current_setup.id,
                            kind=ObservationKind.HORIZONTAL_DISTANCE,
                            from_point=from_pt,
                            to_point=to_pt,
                            value=words[31],
                            target_height=target_h,
                        )
                    )
                if 32 in words:
                    observations.append(
                        RawObservation(
                            id=f"{obs_id_base}-SD",
                            setup_id=current_setup.id,
                            kind=ObservationKind.SLOPE_DISTANCE,
                            from_point=from_pt,
                            to_point=to_pt,
                            value=words[32],
                            target_height=target_h,
                        )
                    )
                if 33 in words:
                    observations.append(
                        RawObservation(
                            id=f"{obs_id_base}-DZ",
                            setup_id=current_setup.id,
                            kind=ObservationKind.HEIGHT_DIFFERENCE,
                            from_point=from_pt,
                            to_point=to_pt,
                            value=words[33],
                            target_height=target_h,
                        )
                    )
        # GSI carries no backsight-azimuth word, so setups come back unoriented.
        # Downstream (`reduce_setup_observations`) then falls back to treating the
        # raw horizontal circle reading as an azimuth. That is a real assumption
        # about the data and the caller should hear about it rather than silently
        # receive bearings that may be meaningless.
        unoriented = sum(1 for s in setups if s.backsight_azimuth is None)
        if unoriented:
            warnings.append(
                f"{unoriented} of {len(setups)} setup(s) have no backsight azimuth; "
                "GSI does not record one. Horizontal circle readings (WI 21) will be "
                "treated as absolute azimuths downstream — supply a backsight to orient them."
            )
        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
        )


def _parse_line(line: str) -> dict[int, float]:
    """Parse one GSI line into a ``{word_id: value}`` mapping.

    GSI scale codes for the most common WIs:
      * ``00``: meters (or whatever native unit; for angles, fractional gons)
      * ``06``: 1 mm
      * ``16``: 0.1 mm
      * ``20``: 100 mm

    For angles: WI 21 / 22 in GSI use either gons (gradians) or DMS
    depending on instrument config. **This parser always reads them as
    DMS** and ignores the scale code — the units flag is not yet read, and
    there is no ``angle_units`` override. The layout consumed is
    ``DD MM SSSSS``, where the trailing five digits are seconds × 1000, so
    90° is ``900000000`` and *not* ``900000`` (which decodes to 0°09'00").
    A gon-configured file will therefore be misread; see the known-gaps
    section of the README.
    """
    out: dict[int, float] = {}
    for m in _WORD_RE.finditer(line):
        wi = int(m.group(1))
        # group(2) is the 2-char info code (we don't currently use it).
        scale_text = m.group(3)
        scale_code = int(scale_text) if scale_text.isdigit() else 0
        sign = 1 if m.group(4) == "+" else -1
        digits = m.group(5)
        # Distance / coordinate / height words use scale codes 0/6/16/20.
        if wi in (31, 32, 33, 81, 82, 83, 84, 85, 87, 88):
            scale = {0: 1.0, 6: 1e-3, 16: 1e-4, 20: 1e-1}.get(scale_code, 1.0)
            out[wi] = sign * int(digits) * scale
        elif wi in (21, 22):
            # DMS-formatted numeric (DDDMMSS.ss embedded as integer string)
            num = int(digits)
            ss = num % 100000
            num //= 100000
            mm = num % 100
            dd = num // 100
            seconds = ss / 1000.0
            out[wi] = sign * (dd + mm / 60.0 + seconds / 3600.0)
        elif wi == 11:
            out[wi] = float(int(digits))
        # Other WIs not consumed yet.
    return out
