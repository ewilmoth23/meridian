"""Pipeline: control network → adjusted coordinates + covariance.

Wraps :mod:`meridian.math.adjustment` so callers pass a domain
:class:`~meridian.domain.network.ControlNetwork` and get a
:class:`~meridian.domain.network.NetworkAdjustment` back.

The pipeline:

1. Builds the parameter index (one ``(x, y, z)`` block per non-fixed
   point).
2. Iterates Gauss-Newton:
   a. Computes observed-minus-computed for every observation.
   b. Builds the Jacobian column-by-column.
   c. Solves with weighted least squares.
   d. Applies parameter corrections; repeats until convergence.
3. Computes posterior covariance and 2-σ error ellipses.
4. Runs the chi-square global test and standardised-residual blunder
   detection.

The Jacobian formulas implemented below are for the most common
observation types (horizontal angle, slope distance, height difference,
GNSS vector). Additional kinds are wired in incrementally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from meridian.domain.network import (
    ConstraintMode,
    ControlNetwork,
    ErrorEllipse,
    NetworkAdjustment,
)
from meridian.domain.observation import (
    AdjustedObservation,
    ObservationKind,
    RawObservation,
)
from meridian.math.adjustment import (
    AdjustmentSpec,
    chi_square_test,
    detect_blunders,
    error_ellipse_2d,
    solve_step,
)


@dataclass(slots=True)
class NetworkAdjustOptions:
    """Tuning knobs for the adjustment."""

    max_iterations: int = 12
    convergence_mm: float = 0.5
    blunder_threshold: float = 3.29
    chi_alpha: float = 0.05


def adjust(
    network: ControlNetwork,
    options: NetworkAdjustOptions | None = None,
) -> NetworkAdjustment:
    """Adjust a control network and return its adjusted coordinates."""
    if options is None:
        options = NetworkAdjustOptions()
    if not network.points:
        raise ValueError("Cannot adjust an empty network.")
    if not network.observations:
        raise ValueError("Cannot adjust a network with no observations.")

    # Parameter ordering: every point gets 3 params (x, y, z). Fixed points
    # are in the index but their columns are zeroed out (effectively).
    point_index: list[str] = [p.id for p in network.points]
    point_lookup: dict[str, int] = {pid: i for i, pid in enumerate(point_index)}

    # Initial parameter vector from a-priori coordinates.
    coords = np.zeros((len(point_index), 3), dtype=np.float64)
    for i, p in enumerate(network.points):
        coords[i, 0] = p.a_priori.x
        coords[i, 1] = p.a_priori.y
        coords[i, 2] = p.a_priori.z

    # Mask of "free" parameters — ones we actually solve for.
    free_mask = _build_free_mask(network, point_lookup)

    iterations = 0
    converged = False
    last_result = None
    while iterations < options.max_iterations:
        spec = _build_jacobian(network, coords, point_lookup, free_mask)
        result = solve_step(spec)
        # Apply corrections (only on free parameters)
        idx_map = np.flatnonzero(free_mask.flatten())
        full_correction = np.zeros(coords.size, dtype=np.float64)
        full_correction[idx_map] = result.x
        coords += full_correction.reshape(coords.shape)
        max_correction = float(np.max(np.abs(full_correction)))
        last_result = result
        iterations += 1
        if max_correction * 1000 < options.convergence_mm:
            converged = True
            break

    assert last_result is not None  # narrow type

    # Build adjusted points.
    from meridian.domain.geometry import Point3D

    adjusted_points: dict[str, Point3D] = {}
    for i, pid in enumerate(point_index):
        adjusted_points[pid] = Point3D(
            x=float(coords[i, 0]),
            y=float(coords[i, 1]),
            z=float(coords[i, 2]),
            crs=network.crs,
            name=pid,
        )

    # Posterior covariance: re-expand to the full parameter space.
    full_cov = np.zeros((coords.size, coords.size), dtype=np.float64)
    idx_map = np.flatnonzero(free_mask.flatten())
    for ai, fa in enumerate(idx_map):
        for bi, fb in enumerate(idx_map):
            full_cov[fa, fb] = last_result.cov_x[ai, bi]

    # Error ellipses (horizontal only) — for each point's 2x2 sub-block.
    ellipses: dict[str, ErrorEllipse] = {}
    for i, pid in enumerate(point_index):
        block = full_cov[3 * i: 3 * i + 2, 3 * i: 3 * i + 2]
        try:
            a, b, theta = error_ellipse_2d(block)
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover
            a, b, theta = 0.0, 0.0, 0.0
        ellipses[pid] = ErrorEllipse(a=a, b=b, theta=theta)

    # Adjusted observation records, with blunder flags.
    blunder_mask = detect_blunders(last_result.standardized, threshold=options.blunder_threshold)
    adjusted_obs: list[AdjustedObservation] = []
    for j, raw in enumerate(network.observations):
        adjusted_value = float(raw.value or 0.0) - float(last_result.v[j])
        adjusted_obs.append(
            AdjustedObservation(
                raw=raw,
                adjusted_value=adjusted_value,
                residual=float(last_result.v[j]),
                sigma_post=float(math.sqrt(max(last_result.sigma0_sq, 0.0))) * (
                    raw.sigma if isinstance(raw.sigma, (int, float)) else 1.0
                ),
                standardized=float(last_result.standardized[j]),
                flagged_as_blunder=bool(blunder_mask[j]),
            )
        )

    return NetworkAdjustment(
        network=network,
        adjusted_points=adjusted_points,
        covariance=full_cov,
        point_index=tuple(point_index),
        error_ellipses=ellipses,
        adjusted_observations=tuple(adjusted_obs),
        sigma0=math.sqrt(max(last_result.sigma0_sq, 0.0)),
        chi_square_passed=chi_square_test(
            last_result.sigma0_sq, last_result.redundancy, alpha=options.chi_alpha
        ),
        iterations=iterations,
        converged=converged,
    )


# ── private helpers ─────────────────────────────────────────────────────────


def _build_free_mask(
    network: ControlNetwork, point_lookup: dict[str, int]
) -> np.ndarray:
    """Boolean ``(N, 3)`` mask: True where the parameter is free to adjust."""
    n = len(network.points)
    mask = np.ones((n, 3), dtype=bool)
    fixed_ids = {p.id for p in network.points if p.fixed}
    if network.constraint_mode is ConstraintMode.MINIMAL:
        # Hold the first fixed point fully (or, if none, the first point).
        anchor = next(iter(fixed_ids), None) or network.points[0].id
        i = point_lookup[anchor]
        mask[i, :] = False
        # And hold the second fixed point's X (or Y) — defines orientation.
        for pid in fixed_ids:
            if pid != anchor:
                j = point_lookup[pid]
                mask[j, 0] = False
                break
    elif network.constraint_mode is ConstraintMode.FREE:
        pass  # no parameters held — solver uses pseudoinverse
    elif network.constraint_mode is ConstraintMode.PARTIAL:
        for pid in fixed_ids:
            mask[point_lookup[pid], :] = False
    elif network.constraint_mode is ConstraintMode.FULL:
        for p in network.points:
            if p.fixed:
                mask[point_lookup[p.id], :] = False
    return mask


def _build_jacobian(
    network: ControlNetwork,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    free_mask: np.ndarray,
) -> AdjustmentSpec:
    """Build the design matrix ``A``, residual vector ``l``, and weights ``w``.

    Each row corresponds to one observation. Columns correspond to the
    *free* parameters in row-major order (``[p1.x, p1.y, p1.z, p2.x, ...]``).
    """
    free_indices = np.flatnonzero(free_mask.flatten())
    n_free = free_indices.size

    rows: list[np.ndarray] = []
    l_vals: list[float] = []
    w_vals: list[float] = []

    for obs in network.observations:
        if obs.rejected:
            continue
        if obs.kind in (
            ObservationKind.HORIZONTAL_ANGLE,
            ObservationKind.AZIMUTH,
        ):
            # Approximate as bearing-from-from-to-to: works for AZIMUTH and
            # short-baseline horizontal angles; v0.2 will split out the
            # full angle-from-three-points formula.
            row, residual, weight = _row_horizontal_bearing(obs, coords, point_lookup, n_free, free_indices)
        elif obs.kind == ObservationKind.SLOPE_DISTANCE:
            row, residual, weight = _row_slope_distance(obs, coords, point_lookup, n_free, free_indices)
        elif obs.kind == ObservationKind.HORIZONTAL_DISTANCE:
            row, residual, weight = _row_horizontal_distance(obs, coords, point_lookup, n_free, free_indices)
        elif obs.kind == ObservationKind.HEIGHT_DIFFERENCE:
            row, residual, weight = _row_height_difference(obs, coords, point_lookup, n_free, free_indices)
        elif obs.kind == ObservationKind.GNSS_VECTOR:
            for sub_row, sub_residual, sub_weight in _rows_gnss_vector(
                obs, coords, point_lookup, n_free, free_indices
            ):
                rows.append(sub_row)
                l_vals.append(sub_residual)
                w_vals.append(sub_weight)
            continue
        else:
            # Unsupported kind — skip; v0.2 will add directional / vertical-angle.
            continue
        rows.append(row)
        l_vals.append(residual)
        w_vals.append(weight)

    if not rows:
        raise ValueError("No usable observations after filtering.")
    return AdjustmentSpec(
        a=np.vstack(rows),
        l=np.asarray(l_vals, dtype=np.float64),
        w=np.asarray(w_vals, dtype=np.float64),
    )


def _to_free_row(local_row: np.ndarray, free_indices: np.ndarray, n_free: int) -> np.ndarray:
    """Project a full-parameter-space row down to free parameters only."""
    out = np.zeros(n_free, dtype=np.float64)
    for k, fi in enumerate(free_indices):
        out[k] = local_row[fi]
    return out


def _coord(coords: np.ndarray, idx: int) -> tuple[float, float, float]:
    return float(coords[idx, 0]), float(coords[idx, 1]), float(coords[idx, 2])


def _row_horizontal_bearing(
    obs: RawObservation,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    n_free: int,
    free_indices: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    if obs.to_point is None or obs.value is None:
        raise ValueError(f"Bearing observation {obs.id} missing to_point or value.")
    i_from = point_lookup[obs.from_point]
    i_to = point_lookup[obs.to_point]
    x1, y1, _ = _coord(coords, i_from)
    x2, y2, _ = _coord(coords, i_to)
    dx = x2 - x1
    dy = y2 - y1
    d2 = dx * dx + dy * dy
    if d2 == 0:
        raise ValueError(f"Bearing observation {obs.id} has coincident endpoints.")
    # ∂az/∂x_to = dy / d², ∂az/∂y_to = -dx / d²; opposite sign on _from.
    full = np.zeros(coords.size, dtype=np.float64)
    full[3 * i_to] = dy / d2
    full[3 * i_to + 1] = -dx / d2
    full[3 * i_from] = -dy / d2
    full[3 * i_from + 1] = dx / d2
    computed = math.atan2(dx, dy) % (2 * math.pi)
    obs_val = obs.value % (2 * math.pi)
    residual = (obs_val - computed + math.pi) % (2 * math.pi) - math.pi
    sigma = float(obs.sigma) if isinstance(obs.sigma, (int, float)) else math.radians(0.001)
    weight = 1.0 / (sigma * sigma)
    return _to_free_row(full, free_indices, n_free), residual, weight


def _row_horizontal_distance(
    obs: RawObservation,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    n_free: int,
    free_indices: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    if obs.to_point is None or obs.value is None:
        raise ValueError(f"Distance observation {obs.id} missing to_point or value.")
    i_from = point_lookup[obs.from_point]
    i_to = point_lookup[obs.to_point]
    x1, y1, _ = _coord(coords, i_from)
    x2, y2, _ = _coord(coords, i_to)
    dx = x2 - x1
    dy = y2 - y1
    d = math.hypot(dx, dy)
    if d == 0:
        raise ValueError(f"Distance observation {obs.id} has coincident endpoints.")
    full = np.zeros(coords.size, dtype=np.float64)
    full[3 * i_to] = dx / d
    full[3 * i_to + 1] = dy / d
    full[3 * i_from] = -dx / d
    full[3 * i_from + 1] = -dy / d
    residual = float(obs.value) - d
    sigma = float(obs.sigma) if isinstance(obs.sigma, (int, float)) else 0.005
    return _to_free_row(full, free_indices, n_free), residual, 1.0 / (sigma * sigma)


def _row_slope_distance(
    obs: RawObservation,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    n_free: int,
    free_indices: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    if obs.to_point is None or obs.value is None:
        raise ValueError(f"Slope distance observation {obs.id} missing to_point or value.")
    i_from = point_lookup[obs.from_point]
    i_to = point_lookup[obs.to_point]
    x1, y1, z1 = _coord(coords, i_from)
    x2, y2, z2 = _coord(coords, i_to)
    dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
    s = math.sqrt(dx * dx + dy * dy + dz * dz)
    if s == 0:
        raise ValueError(f"Slope distance observation {obs.id} has coincident endpoints.")
    full = np.zeros(coords.size, dtype=np.float64)
    full[3 * i_to] = dx / s
    full[3 * i_to + 1] = dy / s
    full[3 * i_to + 2] = dz / s
    full[3 * i_from] = -dx / s
    full[3 * i_from + 1] = -dy / s
    full[3 * i_from + 2] = -dz / s
    residual = float(obs.value) - s
    sigma = float(obs.sigma) if isinstance(obs.sigma, (int, float)) else 0.005
    return _to_free_row(full, free_indices, n_free), residual, 1.0 / (sigma * sigma)


def _row_height_difference(
    obs: RawObservation,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    n_free: int,
    free_indices: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    if obs.to_point is None or obs.value is None:
        raise ValueError(f"Height difference observation {obs.id} missing to_point or value.")
    i_from = point_lookup[obs.from_point]
    i_to = point_lookup[obs.to_point]
    _, _, z1 = _coord(coords, i_from)
    _, _, z2 = _coord(coords, i_to)
    full = np.zeros(coords.size, dtype=np.float64)
    full[3 * i_to + 2] = 1.0
    full[3 * i_from + 2] = -1.0
    residual = float(obs.value) - (z2 - z1)
    sigma = float(obs.sigma) if isinstance(obs.sigma, (int, float)) else 0.002
    return _to_free_row(full, free_indices, n_free), residual, 1.0 / (sigma * sigma)


def _rows_gnss_vector(
    obs: RawObservation,
    coords: np.ndarray,
    point_lookup: dict[str, int],
    n_free: int,
    free_indices: np.ndarray,
) -> list[tuple[np.ndarray, float, float]]:
    """A GNSS vector observation contributes 3 rows (ΔX, ΔY, ΔZ)."""
    if obs.to_point is None or obs.vector is None:
        raise ValueError(f"GNSS vector {obs.id} missing to_point or vector.")
    i_from = point_lookup[obs.from_point]
    i_to = point_lookup[obs.to_point]
    x1, y1, z1 = _coord(coords, i_from)
    x2, y2, z2 = _coord(coords, i_to)
    observed = obs.vector
    computed = (x2 - x1, y2 - y1, z2 - z1)
    sigma = obs.sigma if isinstance(obs.sigma, tuple) else (
        float(obs.sigma) if obs.sigma else 0.005,
    ) * 3
    rows = []
    for axis in range(3):
        full = np.zeros(coords.size, dtype=np.float64)
        full[3 * i_to + axis] = 1.0
        full[3 * i_from + axis] = -1.0
        residual = observed[axis] - computed[axis]
        sig = sigma[axis] if axis < len(sigma) else sigma[-1]
        weight = 1.0 / (float(sig) * float(sig))
        rows.append((_to_free_row(full, free_indices, n_free), residual, weight))
    return rows
