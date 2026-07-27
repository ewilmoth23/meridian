"""Heterogeneous-source fusion entry point.

Wraps :mod:`meridian.pipelines.network_adjust` so callers can hand in
TS + GNSS + LiDAR + photogrammetry tie points + InSAR vectors with
per-source priors, and get a single jointly-adjusted network back.

The strategy:

1. Convert each non-classical source into a stream of
   :class:`RawObservation` records that the underlying
   :func:`meridian.pipelines.network_adjust.adjust` already understands.
2. Apply per-source weight scaling so a poorly-trusted source can't
   dominate the well-instrumented backbone.
3. Run the standard Gauss-Newton.

The conversions live in tiny adapter functions so they're easy to unit
test and easy to extend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from meridian.domain.network import (
    ConstraintMode,
    ControlNetwork,
)
from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
)
from meridian.pipelines.network_adjust import (
    NetworkAdjustOptions,
    adjust,
)

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.network import ControlPoint, NetworkAdjustment


class Source(str, Enum):
    """Provenance label for an observation set."""

    TOTAL_STATION = "total_station"
    GNSS = "gnss"
    LIDAR = "lidar"
    PHOTOGRAMMETRY = "photogrammetry"
    INSAR = "insar"
    AR_FIELD_MARK = "ar_field_mark"


@dataclass(frozen=True, slots=True)
class SourceWeight:
    """Per-source weight prior.

    A scalar multiplier applied to each observation's σ on import. Less
    than 1 means we trust the source more than the supplied σ; greater
    than 1 means we down-weight it.
    """

    sigma_scale: float = 1.0


@dataclass(frozen=True, slots=True)
class FusionInput:
    """One source's contribution to the fusion."""

    source: Source
    observations: tuple[RawObservation, ...]
    weight: SourceWeight = SourceWeight()


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Configuration knobs for a fusion run."""

    constraint_mode: ConstraintMode = ConstraintMode.MINIMAL
    adjustment: NetworkAdjustOptions = field(default_factory=NetworkAdjustOptions)


@dataclass(frozen=True, slots=True)
class FusionResult:
    """Output of a fusion run."""

    adjustment: NetworkAdjustment
    per_source_counts: dict[Source, int]


def fuse(
    *,
    name: str,
    crs: CRS,
    points: tuple[ControlPoint, ...],
    inputs: tuple[FusionInput, ...],
    config: FusionConfig | None = None,
) -> FusionResult:
    """Run a multi-source adjustment.

    Pre-conditions:
    * ``points`` lists every control / unknown point referenced by any
      observation, with a-priori coordinates.
    * Each :class:`FusionInput`'s observations are already in the
      target CRS (no transform happens here).
    """
    config = config or FusionConfig()

    # Re-weight observations per source.
    reweighted: list[RawObservation] = []
    counts: dict[Source, int] = {}
    for inp in inputs:
        counts[inp.source] = len(inp.observations)
        for obs in inp.observations:
            reweighted.append(_apply_weight(obs, inp.weight))

    network = ControlNetwork(
        name=name,
        crs=crs,
        points=points,
        observations=tuple(reweighted),
        constraint_mode=config.constraint_mode,
    )
    adj = adjust(network, config.adjustment)
    return FusionResult(adjustment=adj, per_source_counts=counts)


# ── Source adapters ────────────────────────────────────────────────────────


def lidar_ground_points_to_observations(
    points: list[tuple[str, float, float, float, float]],
    *,
    setup_id: str = "LIDAR",
) -> tuple[RawObservation, ...]:
    """Convert classified LiDAR ground points to absolute-position observations.

    Each tuple is ``(point_id, x, y, z, sigma)``. Each becomes a single
    GNSS-position-style observation pinning that point's coordinates,
    weighted by ``sigma``.
    """
    out: list[RawObservation] = []
    for pid, x, y, z, sigma in points:
        out.append(
            RawObservation(
                id=f"LIDAR-{pid}",
                setup_id=setup_id,
                kind=ObservationKind.GNSS_POSITION,
                from_point=pid,
                to_point=None,
                vector=(x, y, z),
                sigma=(sigma, sigma, sigma * 1.5),
            )
        )
    return tuple(out)


def photogrammetry_tie_points_to_observations(
    pairs: list[tuple[str, str, float, float, float, float]],
    *,
    setup_id: str = "SFM",
) -> tuple[RawObservation, ...]:
    """Convert SfM tie-point pairs into baseline observations.

    Each tuple is ``(from_pt, to_pt, dx, dy, dz, sigma)``.
    """
    return tuple(
        RawObservation(
            id=f"TIE-{frm}-{to}",
            setup_id=setup_id,
            kind=ObservationKind.GNSS_VECTOR,
            from_point=frm,
            to_point=to,
            vector=(dx, dy, dz),
            sigma=(s, s, s),
        )
        for frm, to, dx, dy, dz, s in pairs
    )


def insar_motion_to_observations(
    motions: list[tuple[str, float, float, float, float]],
    *,
    setup_id: str = "INSAR",
    epoch_label: str = "T1",
) -> tuple[RawObservation, ...]:
    """Convert InSAR Δposition vectors to GNSS-vector observations.

    Each tuple is ``(point_id_at_epoch, dx, dy, dz, sigma)``. The
    observation pins the change between the prior epoch and this one;
    higher-order multi-epoch fusion lands in v0.7.
    """
    return tuple(
        RawObservation(
            id=f"INSAR-{pid}-{epoch_label}",
            setup_id=setup_id,
            kind=ObservationKind.GNSS_VECTOR,
            from_point=f"{pid}@T0",
            to_point=f"{pid}@{epoch_label}",
            vector=(dx, dy, dz),
            sigma=(s, s, s * 2.0),       # vertical InSAR is poorly constrained
        )
        for pid, dx, dy, dz, s in motions
    )


# ── private ────────────────────────────────────────────────────────────────


def _apply_weight(obs: RawObservation, weight: SourceWeight) -> RawObservation:
    if weight.sigma_scale == 1.0 or obs.sigma is None:
        return obs
    new_sigma: float | tuple[float, float, float]
    if isinstance(obs.sigma, tuple):
        new_sigma = tuple(s * weight.sigma_scale for s in obs.sigma)  # type: ignore[assignment]
    else:
        new_sigma = float(obs.sigma) * weight.sigma_scale
    return RawObservation(
        id=obs.id,
        setup_id=obs.setup_id,
        kind=obs.kind,
        from_point=obs.from_point,
        to_point=obs.to_point,
        value=obs.value,
        vector=obs.vector,
        sigma=new_sigma,
        target_height=obs.target_height,
        azimuth_reference=obs.azimuth_reference,
        timestamp=obs.timestamp,
        rejected=obs.rejected,
        rejection_reason=obs.rejection_reason,
        extra=dict(obs.extra),
    )
