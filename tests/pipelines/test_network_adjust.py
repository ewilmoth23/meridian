"""Slice 2 network adjustment pipeline test — minimal triangle."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS
from meridian.domain.geometry import Point3D
from meridian.domain.network import (
    ConstraintMode,
    ControlNetwork,
    ControlPoint,
    MonumentType,
)
from meridian.domain.observation import ObservationKind, RawObservation
from meridian.pipelines.network_adjust import NetworkAdjustOptions, adjust


@pytest.fixture()
def crs():
    return CRS(epsg=2277)


def test_adjust_minimal_triangle_distances(crs):
    # Three points forming a 3-4-5 triangle. Two are fixed, one is solved.
    p1 = ControlPoint(
        id="P1",
        a_priori=Point3D(0, 0, 0, crs, name="P1"),
        fixed=True,
        monument=MonumentType.BRASS_DISK,
    )
    p2 = ControlPoint(
        id="P2",
        a_priori=Point3D(3, 0, 0, crs, name="P2"),
        fixed=True,
        monument=MonumentType.BRASS_DISK,
    )
    p3 = ControlPoint(
        id="P3",
        a_priori=Point3D(2.9, 3.9, 0, crs, name="P3"),  # rough start
        fixed=False,
        monument=MonumentType.IRON_PIN_SET,
    )
    obs = [
        RawObservation(
            id="d12", setup_id="S1", kind=ObservationKind.HORIZONTAL_DISTANCE,
            from_point="P1", to_point="P2", value=3.0, sigma=0.005,
        ),
        RawObservation(
            id="d13", setup_id="S2", kind=ObservationKind.HORIZONTAL_DISTANCE,
            from_point="P1", to_point="P3", value=5.0, sigma=0.005,
        ),
        RawObservation(
            id="d23", setup_id="S3", kind=ObservationKind.HORIZONTAL_DISTANCE,
            from_point="P2", to_point="P3", value=4.0, sigma=0.005,
        ),
    ]
    network = ControlNetwork(
        name="triangle",
        crs=crs,
        points=(p1, p2, p3),
        observations=tuple(obs),
        constraint_mode=ConstraintMode.PARTIAL,
    )
    result = adjust(network, NetworkAdjustOptions(max_iterations=20, convergence_mm=0.1))
    p3_adj = result.adjusted_points["P3"]
    # The exact answer for a 3-4-5 triangle with P1=(0,0), P2=(3,0):
    # P3 = (3, 4). (Two solutions; the iteration starting near (2.9, 3.9) finds (3,4).)
    assert p3_adj.x == pytest.approx(3.0, abs=1e-3)
    assert p3_adj.y == pytest.approx(4.0, abs=1e-3)
    assert result.iterations >= 1
    assert result.converged
