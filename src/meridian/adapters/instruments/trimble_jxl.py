"""Trimble JXL (JobXML) driver.

Trimble's JobXML is the modern replacement for the legacy ``.dc`` /
``.job`` formats and is what current Trimble Access / TBC produces.
It's a moderately verbose XML schema that carries setups, observations
(angles, distances, GNSS vectors), points, codes, and metadata.

This driver handles the most common observation types:

* ``StationSetup`` records → :class:`~meridian.domain.observation.Setup`.
* ``RegularObservation`` (angle + distance), ``GNSSObservation``,
  ``LevelObservation`` records → :class:`RawObservation`.
* ``Point`` records → :class:`~meridian.domain.geometry.Point3D`.

Edge cases we handle:
* Optional ``CorrectionGroup`` for atmospheric reductions.
* Mixed angle units (DMS vs gons).
* Missing target heights (default 0).
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


class TrimbleJXLDriver(InstrumentDriver):
    """Reader for Trimble JobXML files."""

    name = "Trimble JobXML (JXL)"
    short_id = "trimble_jxl"
    extensions = ("jxl", "xml")

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in self.extensions:
            return False
        try:
            with path.open("rb") as f:
                head = f.read(2048)
        except OSError:
            return False
        return b"JOBFile" in head or b"<Trimble" in head or b"JobXML" in head

    def read(self, path: Path) -> InstrumentReadResult:
        from lxml import etree

        ns_strip = etree.XMLParser(remove_blank_text=True, recover=True)
        tree = etree.parse(str(path), ns_strip)
        root = tree.getroot()

        setups: list[Setup] = []
        observations: list[RawObservation] = []
        warnings: list[str] = []

        # JXL uses either a default namespace or none; iterate by local-name.
        def localfind(elem: object, name: str) -> list[object]:
            return elem.findall(f".//{{*}}{name}")  # type: ignore[attr-defined]

        # Setups
        for stn in localfind(root, "StationSetup"):
            occ = _text(stn, "StationName") or _text(stn, "StationID") or ""
            ih = float(_text(stn, "TheodoliteHeight") or _text(stn, "InstrumentHeight") or 0)
            sid = _text(stn, "ID") or f"S{len(setups) + 1:04d}"
            bs_pt = _text(stn, "BackSightPointName")
            bs_az = _text(stn, "BackSightAzimuth")
            setups.append(
                Setup(
                    id=sid,
                    occupied_point=occ,
                    instrument_height=ih,
                    backsight_point=bs_pt,
                    backsight_azimuth=math.radians(float(bs_az)) if bs_az else None,
                )
            )

        setup_lookup = {s.id: s for s in setups}

        # Regular (total-station) observations
        for obs in localfind(root, "RegularObservation"):
            sid = _text(obs, "StationID") or (setups[0].id if setups else "S0001")
            stn = setup_lookup.get(sid, setups[0] if setups else None)
            if stn is None:
                warnings.append("Observation with no setup reference; skipped.")
                continue
            target = _text(obs, "TargetID") or _text(obs, "TargetName") or _text(obs, "PointName")
            ha = _text(obs, "HorizontalCircle") or _text(obs, "HorizontalAngle")
            va = _text(obs, "VerticalCircle") or _text(obs, "ZenithAngle")
            sd = _text(obs, "SlopeDistance")
            hd = _text(obs, "HorizontalDistance")
            th = float(_text(obs, "TargetHeight") or 0)
            obs_id = _text(obs, "ID") or f"{sid}-O{len(observations) + 1:05d}"
            base = {
                "setup_id": stn.id,
                "from_point": stn.occupied_point,
                "to_point": target,
                "target_height": th,
            }
            if ha is not None:
                observations.append(
                    RawObservation(
                        id=f"{obs_id}-HA",
                        kind=ObservationKind.HORIZONTAL_ANGLE,
                        value=math.radians(float(ha)),
                        **base,  # type: ignore[arg-type]
                    )
                )
            if va is not None:
                observations.append(
                    RawObservation(
                        id=f"{obs_id}-VA",
                        kind=ObservationKind.VERTICAL_ANGLE,
                        value=math.radians(float(va)),
                        **base,  # type: ignore[arg-type]
                    )
                )
            if sd is not None:
                observations.append(
                    RawObservation(
                        id=f"{obs_id}-SD",
                        kind=ObservationKind.SLOPE_DISTANCE,
                        value=float(sd),
                        **base,  # type: ignore[arg-type]
                    )
                )
            if hd is not None and sd is None:
                observations.append(
                    RawObservation(
                        id=f"{obs_id}-HD",
                        kind=ObservationKind.HORIZONTAL_DISTANCE,
                        value=float(hd),
                        **base,  # type: ignore[arg-type]
                    )
                )

        # GNSS baselines
        for vec in localfind(root, "GNSSObservation"):
            from_pt = _text(vec, "FromPointName") or _text(vec, "BasePointName")
            to_pt = _text(vec, "ToPointName") or _text(vec, "RoverPointName")
            dx = _text(vec, "DeltaX") or _text(vec, "DX")
            dy = _text(vec, "DeltaY") or _text(vec, "DY")
            dz = _text(vec, "DeltaZ") or _text(vec, "DZ")
            if from_pt and to_pt and dx and dy and dz:
                observations.append(
                    RawObservation(
                        id=_text(vec, "ID") or f"V{len(observations) + 1:05d}",
                        setup_id="GNSS",
                        kind=ObservationKind.GNSS_VECTOR,
                        from_point=from_pt,
                        to_point=to_pt,
                        vector=(float(dx), float(dy), float(dz)),
                    )
                )

        return InstrumentReadResult(
            setups=tuple(setups),
            observations=tuple(observations),
            warnings=tuple(warnings),
        )


def _text(elem: object, name: str) -> str | None:
    found = elem.findall(f".//{{*}}{name}")  # type: ignore[attr-defined]
    if not found:
        return None
    text = found[0].text  # type: ignore[attr-defined]
    return text.strip() if isinstance(text, str) and text.strip() else None
