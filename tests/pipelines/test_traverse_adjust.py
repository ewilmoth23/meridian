"""Slice 3 traverse pipeline tests."""

from __future__ import annotations

import math

import pytest

from meridian.domain.observation import (
    ObservationKind,
    RawObservation,
    Setup,
)
from meridian.pipelines.traverse_adjust import (
    reduce_setup_observations,
    run_closed_traverse,
)


def _square_setups_and_observations():
    # Manually construct four setups simulating a square traverse.
    # Each setup occupies one corner with backsight to previous corner,
    # and observes the next corner at a horizontal distance of 100 m.
    setups = [
        Setup(id=f"S{i+1}", occupied_point=f"P{i+1}", instrument_height=1.5,
              backsight_azimuth=math.radians(angle_from_prev))
        for i, angle_from_prev in enumerate([180, 270, 0, 90])
    ]
    obs = []
    targets = ["P2", "P3", "P4", "P1"]
    # The setup's backsight is the *previous* leg's azimuth, but our reducer
    # just adds HA to backsight_azimuth — so set HA = (90° turn) = π/2 radians.
    # To make the legs travel north, east, south, west in turn, we set:
    #   leg 1 azimuth = 0   (north)
    #   leg 2 azimuth = π/2 (east)
    #   leg 3 azimuth = π   (south)
    #   leg 4 azimuth = 3π/2 (west)
    # Backsight azimuths above are leg azimuths - π/2 (the angle turned),
    # so HA = π/2 makes (backsight + HA) = correct leg azimuth.
    for i, target in enumerate(targets):
        obs.append(
            RawObservation(
                id=f"O{i+1}-HA",
                setup_id=f"S{i+1}",
                kind=ObservationKind.HORIZONTAL_ANGLE,
                from_point=f"P{i+1}",
                to_point=target,
                value=math.pi / 2,
                target_height=1.5,
            )
        )
        obs.append(
            RawObservation(
                id=f"O{i+1}-HD",
                setup_id=f"S{i+1}",
                kind=ObservationKind.HORIZONTAL_DISTANCE,
                from_point=f"P{i+1}",
                to_point=target,
                value=100.0,
                target_height=1.5,
            )
        )
    return setups, obs


def test_reduce_setup_observations_yields_legs_per_setup():
    setups, obs = _square_setups_and_observations()
    legs = reduce_setup_observations(setups, obs)
    assert len(legs) == 4


def test_run_closed_traverse_compass_closes_perfectly():
    setups, obs = _square_setups_and_observations()
    legs = reduce_setup_observations(setups, obs)
    res = run_closed_traverse(legs, starting_point=(0.0, 0.0), method="compass")
    assert res.closure_distance == pytest.approx(0.0, abs=1e-9)
    assert res.perimeter == pytest.approx(400.0)
    assert abs(res.area) == pytest.approx(10000.0, abs=1e-6)
