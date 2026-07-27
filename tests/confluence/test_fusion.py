"""Confluence multi-source fusion tests."""

from __future__ import annotations

import pytest

from meridian.confluence import (
    FusionConfig,
    FusionInput,
    SourceWeight,
    fuse,
)
from meridian.confluence.fusion import (
    Source,
    insar_motion_to_observations,
    lidar_ground_points_to_observations,
    photogrammetry_tie_points_to_observations,
)
from meridian.domain.crs import CRS
from meridian.domain.geometry import Point3D
from meridian.domain.network import ConstraintMode, ControlPoint, MonumentType
from meridian.domain.observation import ObservationKind, RawObservation


@pytest.fixture()
def crs():
    return CRS(epsg=2277)


def _ts_obs(*args, **kwargs):
    return RawObservation(*args, **kwargs)


def test_lidar_adapter_creates_position_observations():
    pts = [
        ("P1", 100.0, 200.0, 50.0, 0.05),
        ("P2", 110.0, 200.0, 50.5, 0.07),
    ]
    obs = lidar_ground_points_to_observations(pts)
    assert len(obs) == 2
    assert obs[0].kind == ObservationKind.GNSS_POSITION
    assert obs[0].vector == (100.0, 200.0, 50.0)


def test_photogrammetry_adapter_creates_baselines():
    pairs = [("P1", "P2", 10.0, 0.0, 0.5, 0.02)]
    obs = photogrammetry_tie_points_to_observations(pairs)
    assert obs[0].kind == ObservationKind.GNSS_VECTOR
    assert obs[0].from_point == "P1"
    assert obs[0].to_point == "P2"


def test_insar_adapter_uses_epoch_labels():
    motions = [("P1", 0.001, 0.002, -0.005, 0.001)]
    obs = insar_motion_to_observations(motions, epoch_label="T2")
    assert obs[0].from_point == "P1@T0"
    assert obs[0].to_point == "P1@T2"


def test_weight_scaling_propagates_to_obs(crs):
    p1 = ControlPoint(id="P1", a_priori=Point3D(0, 0, 0, crs), fixed=True, monument=MonumentType.BRASS_DISK)
    p2 = ControlPoint(id="P2", a_priori=Point3D(3, 0, 0, crs), fixed=True, monument=MonumentType.BRASS_DISK)
    p3 = ControlPoint(id="P3", a_priori=Point3D(2.9, 3.9, 0, crs), fixed=False, monument=MonumentType.IRON_PIN_SET)
    ts_obs = (
        RawObservation(id="d12", setup_id="S", kind=ObservationKind.HORIZONTAL_DISTANCE,
                       from_point="P1", to_point="P2", value=3.0, sigma=0.005),
        RawObservation(id="d13", setup_id="S", kind=ObservationKind.HORIZONTAL_DISTANCE,
                       from_point="P1", to_point="P3", value=5.0, sigma=0.005),
        RawObservation(id="d23", setup_id="S", kind=ObservationKind.HORIZONTAL_DISTANCE,
                       from_point="P2", to_point="P3", value=4.0, sigma=0.005),
    )
    inputs = (
        FusionInput(source=Source.TOTAL_STATION, observations=ts_obs, weight=SourceWeight(sigma_scale=1.0)),
    )
    res = fuse(
        name="triangle",
        crs=crs,
        points=(p1, p2, p3),
        inputs=inputs,
        config=FusionConfig(constraint_mode=ConstraintMode.PARTIAL),
    )
    p3_adj = res.adjustment.adjusted_points["P3"]
    assert p3_adj.x == pytest.approx(3.0, abs=1e-3)
    assert p3_adj.y == pytest.approx(4.0, abs=1e-3)
    assert res.per_source_counts[Source.TOTAL_STATION] == 3
