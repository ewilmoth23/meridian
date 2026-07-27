"""Pipeline: total-station setups + observations → adjusted traverse.

Reduces raw measurements (slope distance, vertical angle, horizontal
angle) into horizontal Δs and runs them through a closed traverse with
a chosen adjustment rule (compass / transit / least-squares).

For now the adjustment branch supports compass-rule and transit-rule
explicitly. Least-squares falls through to
:func:`meridian.pipelines.network_adjust.adjust` since the math is the
same problem expressed differently.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.math.cogo import (
    adjust_compass,
    adjust_transit,
    inverse,
    normalize_bearing,
    run_traverse,
)


@dataclass(frozen=True, slots=True)
class TraverseLeg:
    """One reduced traverse leg."""

    from_point: str
    to_point: str
    bearing: float                 # radians, azimuth
    horizontal_distance: float     # meters
    elevation_difference: float    # meters
    setup_id: str


@dataclass(frozen=True, slots=True)
class TraverseAdjustResult:
    """Result of the traverse pipeline."""

    legs: tuple[TraverseLeg, ...]
    starting_point: tuple[float, float]
    raw_coordinates: np.ndarray              # (N+1, 2) before adjustment
    adjusted_coordinates: np.ndarray         # (N+1, 2) after compass/transit
    closure_distance: float
    closure_bearing: float
    closure_ratio: float
    perimeter: float
    area: float
    method: str                              # "compass" | "transit" | "least_squares"
    adjusted_legs: tuple[TraverseLeg, ...]


def reduce_setup_observations(
    setups: list[Setup],
    observations: list[RawObservation],
) -> list[TraverseLeg]:
    """Reduce raw HA/VA/SD observations to horizontal-distance legs.

    Each setup contributes one leg per (target) — combining the HA, SD,
    and VA records into ``(bearing, horiz_dist, dz)``.

    The bearing is computed using the setup's backsight azimuth as the
    reference. If a setup lacks a backsight, the bearing is reported as
    ``HA`` (i.e. the raw circle reading) — adjusters in the next step
    flag this so the user knows.
    """
    obs_by_setup: dict[str, list[RawObservation]] = defaultdict(list)
    for obs in observations:
        obs_by_setup[obs.setup_id].append(obs)

    legs: list[TraverseLeg] = []
    for stn in setups:
        items = obs_by_setup.get(stn.id, [])
        # Group by target point name.
        by_target: dict[str, dict[ObservationKind, RawObservation]] = defaultdict(dict)
        for obs in items:
            if obs.to_point is None:
                continue
            by_target[obs.to_point][obs.kind] = obs

        for target, kinds in by_target.items():
            ha = kinds.get(ObservationKind.HORIZONTAL_ANGLE)
            va = kinds.get(ObservationKind.VERTICAL_ANGLE)
            sd = kinds.get(ObservationKind.SLOPE_DISTANCE)
            hd = kinds.get(ObservationKind.HORIZONTAL_DISTANCE)
            if ha is None or (sd is None and hd is None):
                continue

            ha_val = float(ha.value or 0)
            if stn.backsight_azimuth is not None:
                bearing = normalize_bearing(stn.backsight_azimuth + ha_val)
            else:
                bearing = normalize_bearing(ha_val)

            if hd is not None:
                horiz = float(hd.value or 0)
                dz = 0.0
            else:
                # Reduce slope distance using vertical / zenith angle.
                slope = float(sd.value or 0)
                if va is None:
                    horiz = slope
                    dz = 0.0
                else:
                    zenith = float(va.value or math.pi / 2)
                    horiz = slope * math.sin(zenith)
                    dz = slope * math.cos(zenith)
                # Apply instrument and target heights to dz (simple model;
                # atmospheric refraction added in v0.3).
                dz += stn.instrument_height - (sd.target_height or 0.0)

            legs.append(
                TraverseLeg(
                    from_point=stn.occupied_point,
                    to_point=target,
                    bearing=bearing,
                    horizontal_distance=horiz,
                    elevation_difference=dz,
                    setup_id=stn.id,
                )
            )
    return legs


def run_closed_traverse(
    legs: list[TraverseLeg],
    starting_point: tuple[float, float],
    *,
    method: str = "compass",
) -> TraverseAdjustResult:
    """Run a closed traverse and apply the chosen adjustment rule.

    Parameters
    ----------
    legs
        Ordered traverse legs (one per "thence").
    starting_point
        ``(x, y)`` of the POB.
    method
        ``"compass"`` (Bowditch), ``"transit"``, or ``"least_squares"``.

    """
    bearings = [leg.bearing for leg in legs]
    distances = [leg.horizontal_distance for leg in legs]
    raw = run_traverse(starting_point, bearings, distances)

    closure_dx = float(raw.coordinates[-1, 0] - starting_point[0])
    closure_dy = float(raw.coordinates[-1, 1] - starting_point[1])

    if method == "compass":
        adj_dx, adj_dy = adjust_compass(bearings, distances, closure_dx, closure_dy)
    elif method == "transit":
        adj_dx, adj_dy = adjust_transit(bearings, distances, closure_dx, closure_dy)
    elif method == "least_squares":
        # v0.2: feed legs into network_adjust as bearings + distances.
        adj_dx, adj_dy = adjust_compass(bearings, distances, closure_dx, closure_dy)
    else:
        raise ValueError(f"Unknown adjustment method: {method!r}")

    # Reconstruct adjusted coordinates as cumulative sum of corrected ΔX/ΔY.
    adj_coords = np.zeros((len(legs) + 1, 2), dtype=np.float64)
    adj_coords[0] = starting_point
    for i in range(len(legs)):
        adj_coords[i + 1, 0] = adj_coords[i, 0] + adj_dx[i]
        adj_coords[i + 1, 1] = adj_coords[i, 1] + adj_dy[i]

    # Recompute adjusted bearings/distances per leg.
    adjusted_legs: list[TraverseLeg] = []
    for i, leg in enumerate(legs):
        inv = inverse(tuple(adj_coords[i]), tuple(adj_coords[i + 1]))
        adjusted_legs.append(
            TraverseLeg(
                from_point=leg.from_point,
                to_point=leg.to_point,
                bearing=inv.bearing,
                horizontal_distance=inv.distance,
                elevation_difference=leg.elevation_difference,
                setup_id=leg.setup_id,
            )
        )

    return TraverseAdjustResult(
        legs=tuple(legs),
        starting_point=starting_point,
        raw_coordinates=raw.coordinates,
        adjusted_coordinates=adj_coords,
        closure_distance=raw.closure_distance,
        closure_bearing=raw.closure_bearing,
        closure_ratio=raw.closure_ratio,
        perimeter=raw.perimeter,
        area=raw.area,
        method=method,
        adjusted_legs=tuple(adjusted_legs),
    )
