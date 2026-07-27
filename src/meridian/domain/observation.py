"""Field observation entities.

Models the raw and adjusted measurements that come out of total stations,
GNSS receivers, and digital levels. These are the *input* to the network
adjustment pipeline; adjusted values are the *output*.

A note on conventions:

* All angles in :class:`RawObservation` and :class:`AdjustedObservation`
  are stored in **radians**. Adapters convert to/from DMS, gons, mils.
* Distances are stored in **meters** internally regardless of the
  instrument's native unit. Adapters convert.
* Bearings (in :class:`RawObservation`) are azimuths measured clockwise
  from grid / true / magnetic north — the ``reference`` field says which.
* Standard deviations in :class:`RawObservation.sigma` are 1-σ a priori
  estimates used as observation weights in the adjustment.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ObservationKind(str, Enum):
    """The kind of measurement an observation represents."""

    HORIZONTAL_ANGLE = "horizontal_angle"   # at-from-to triple, radians
    VERTICAL_ANGLE = "vertical_angle"       # at-to pair, radians (zenith)
    DIRECTION = "direction"                 # at-to direction (one of a set), radians
    SLOPE_DISTANCE = "slope_distance"       # at-to slope distance, meters
    HORIZONTAL_DISTANCE = "horizontal_distance"  # reduced, meters
    HEIGHT_DIFFERENCE = "height_difference" # leveling Δh, meters
    AZIMUTH = "azimuth"                     # at-to grid/true/magnetic azimuth, radians
    GNSS_VECTOR = "gnss_vector"             # ΔX, ΔY, ΔZ baseline in ECEF, meters
    GNSS_POSITION = "gnss_position"         # absolute position fix, ECEF or geographic


class AzimuthReference(str, Enum):
    """Reference frame for an azimuth observation."""

    TRUE_NORTH = "true_north"
    GRID_NORTH = "grid_north"
    MAGNETIC_NORTH = "magnetic_north"
    ASSUMED = "assumed"


@dataclass(frozen=True, slots=True)
class Setup:
    """An instrument setup: where the instrument was, what it was aimed at,
    and the geometry needed to reduce its observations.

    A traverse / network is a series of setups; each setup hosts one or
    more :class:`RawObservation` records.
    """

    id: str
    occupied_point: str          # name / id of point under the instrument
    instrument_height: float     # meters above the point
    timestamp: dt.datetime | None = None
    instrument_serial: str | None = None
    backsight_point: str | None = None
    backsight_azimuth: float | None = None  # radians, if known a priori
    notes: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawObservation:
    """A single raw measurement.

    ``from_point`` and ``to_point`` are the names/ids of points (resolved
    against the survey's point catalog). For setups that occupy a control
    point, ``from_point`` matches the setup's ``occupied_point``.

    ``value`` is interpreted according to ``kind``:

    * angle / azimuth → radians
    * distance / height-difference → meters
    * gnss vector → ``(dx, dy, dz)`` triple in meters; stored in ``vector``

    ``sigma`` is the 1-σ a priori standard deviation for the observation
    in the same units as ``value`` (or ``vector``). Used as the weight in
    the network adjustment.
    """

    id: str
    setup_id: str
    kind: ObservationKind
    from_point: str
    to_point: str | None
    value: float | None = None                              # scalar observations
    vector: tuple[float, float, float] | None = None        # GNSS baselines
    sigma: float | tuple[float, float, float] | None = None
    target_height: float | None = None                      # meters above to_point
    azimuth_reference: AzimuthReference | None = None
    timestamp: dt.datetime | None = None
    rejected: bool = False
    rejection_reason: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scalar_kinds = {
            ObservationKind.HORIZONTAL_ANGLE,
            ObservationKind.VERTICAL_ANGLE,
            ObservationKind.DIRECTION,
            ObservationKind.SLOPE_DISTANCE,
            ObservationKind.HORIZONTAL_DISTANCE,
            ObservationKind.HEIGHT_DIFFERENCE,
            ObservationKind.AZIMUTH,
        }
        if self.kind in scalar_kinds and self.value is None:
            raise ValueError(f"{self.kind} requires a scalar value.")
        if self.kind == ObservationKind.GNSS_VECTOR and self.vector is None:
            raise ValueError("GNSS_VECTOR requires a vector (dx, dy, dz).")


@dataclass(frozen=True, slots=True)
class AdjustedObservation:
    """An observation after least-squares adjustment.

    ``residual`` is the post-adjustment correction (observed − adjusted).
    ``sigma_post`` is the a posteriori standard deviation. ``standardized``
    is the studentized residual used for blunder detection.
    """

    raw: RawObservation
    adjusted_value: float | tuple[float, float, float]
    residual: float | tuple[float, float, float]
    sigma_post: float | tuple[float, float, float]
    standardized: float
    flagged_as_blunder: bool = False
