"""Control point and network entities.

A :class:`ControlNetwork` is a graph of control points connected by
observations. The output of running it through
:func:`meridian.pipelines.network_adjust.adjust` is a
:class:`NetworkAdjustment`, which carries the adjusted coordinates,
covariance, and per-point error ellipses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point3D
    from meridian.domain.observation import AdjustedObservation, RawObservation


class ConstraintMode(str, Enum):
    """How the adjustment is constrained."""

    FREE = "free"
    """Inner constraints; only differences in coordinates are determined."""

    MINIMAL = "minimal"
    """Hold one point fixed (and one azimuth) — defines the datum."""

    PARTIAL = "partial"
    """Hold a subset of points; weight others as known with prior σ."""

    FULL = "full"
    """All control points held fixed; only new points adjusted."""


class MonumentType(str, Enum):
    """Physical monument category — mirrors industry common types."""

    IRON_PIN_FOUND = "iron_pin_found"
    IRON_PIN_SET = "iron_pin_set"
    REBAR_CAP_FOUND = "rebar_cap_found"
    REBAR_CAP_SET = "rebar_cap_set"
    BRASS_DISK = "brass_disk"
    CONCRETE_MONUMENT = "concrete_monument"
    PK_NAIL = "pk_nail"
    MAG_NAIL = "mag_nail"
    BENCHMARK = "benchmark"
    GPS_REFERENCE = "gps_reference"
    CALCULATED = "calculated"
    UNDEFINED = "undefined"


@dataclass(frozen=True, slots=True)
class ControlPoint:
    """A control point — a survey marker with known (or to-be-determined)
    coordinates.

    Whether a point is *fixed* in an adjustment is decided by the
    adjustment configuration, not by the point itself. A ``ControlPoint``
    just carries metadata + an a priori coordinate guess (the adjustment's
    starting point) plus the prior-σ on each axis when relevant.
    """

    id: str                        # unique within the survey
    a_priori: Point3D
    code: str | None = None        # field code / feature code (CL, FL, GP, …)
    monument: MonumentType = MonumentType.UNDEFINED
    description: str | None = None
    sigma_xyz: tuple[float, float, float] | None = None
    fixed: bool = False
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorEllipse:
    """2-σ error ellipse on a horizontal point.

    ``a`` and ``b`` are the semi-axes in the units of the network's CRS;
    ``theta`` is the rotation of the ``a`` axis from the +x axis, in radians.
    """

    a: float
    b: float
    theta: float

    def to_dict(self) -> dict[str, float]:
        return {"a": self.a, "b": self.b, "theta": self.theta}


@dataclass(frozen=True, slots=True)
class ControlNetwork:
    """A control network ready to adjust.

    It is intentionally a *value object*: just the inputs to the
    adjustment. The output is a :class:`NetworkAdjustment`.
    """

    name: str
    crs: CRS
    points: tuple[ControlPoint, ...]
    observations: tuple[RawObservation, ...]
    constraint_mode: ConstraintMode = ConstraintMode.MINIMAL


@dataclass(frozen=True, slots=True)
class NetworkAdjustment:
    """The output of adjusting a network.

    Attributes
    ----------
    network
        The input network (kept for traceability).
    adjusted_points
        Mapping of point id → adjusted :class:`Point3D`.
    covariance
        Posterior covariance matrix; rows/columns are flattened by
        ``[x_p1, y_p1, z_p1, x_p2, y_p2, z_p2, …]`` order.
    point_index
        The order of point ids matching :attr:`covariance` rows.
    error_ellipses
        Mapping of point id → 2-σ horizontal error ellipse.
    adjusted_observations
        One per input observation, in the same order.
    sigma0
        Reference variance (a posteriori); ``1.0`` when chi-square test
        passes.
    chi_square_passed
        Whether the global F-test on ``sigma0`` passed at α = 0.05.
    iterations
        Number of Gauss-Newton iterations to convergence.
    converged
        Whether the adjustment converged within the iteration limit.

    """

    network: ControlNetwork
    adjusted_points: dict[str, Point3D]
    covariance: np.ndarray
    point_index: tuple[str, ...]
    error_ellipses: dict[str, ErrorEllipse]
    adjusted_observations: tuple[AdjustedObservation, ...]
    sigma0: float
    chi_square_passed: bool
    iterations: int
    converged: bool

    def std_at(self, point_id: str) -> tuple[float, float, float]:
        """Posterior standard deviation (σx, σy, σz) for a point."""
        i = self.point_index.index(point_id)
        return (
            float(self.covariance[3 * i, 3 * i] ** 0.5),
            float(self.covariance[3 * i + 1, 3 * i + 1] ** 0.5),
            float(self.covariance[3 * i + 2, 3 * i + 2] ** 0.5),
        )
