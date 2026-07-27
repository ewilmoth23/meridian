"""Echo (sun, GCP, mission) tests."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from meridian.echo import (
    AccuracyTarget,
    MissionConfig,
    SunCriteria,
    plan_gcps,
    plan_grid_mission,
    sun_position,
    sun_windows,
)

# ── sun_angle ──────────────────────────────────────────────────────────────


def test_sun_position_solar_noon_austin_summer_high():
    # 30°N, summer noon — sun should be very high (>70°).
    when = dt.datetime(2026, 6, 21, 18, 0, tzinfo=dt.UTC)  # 1pm CDT
    alt, az = sun_position(when, lat_deg=30.27, lon_deg=-97.74)
    assert alt > 70.0
    assert 100.0 < az < 260.0


def test_sun_position_midnight_below_horizon():
    when = dt.datetime(2026, 6, 21, 6, 0, tzinfo=dt.UTC)  # 1am CDT
    alt, _ = sun_position(when, lat_deg=30.27, lon_deg=-97.74)
    assert alt < 0


def test_sun_position_requires_tz():
    with pytest.raises(ValueError):
        sun_position(dt.datetime(2026, 6, 21, 12, 0), 30.0, -97.0)


def test_sun_windows_yields_morning_and_afternoon_bands():
    windows = sun_windows(
        date=dt.date(2026, 6, 21),
        lat_deg=30.27,
        lon_deg=-97.74,
        criteria=SunCriteria(min_altitude_deg=30.0, max_altitude_deg=60.0),
        step_minutes=15,
    )
    # On a Texas summer day, the 30-60° window happens twice (morning + late afternoon).
    assert len(windows) >= 2
    assert all(w.duration_minutes > 0 for w in windows)


# ── GCP planner ────────────────────────────────────────────────────────────


def test_plan_gcps_minimum_four_for_small_aoi():
    polygon = np.array([[0, 0], [50, 0], [50, 50], [0, 50], [0, 0]], dtype=np.float64)
    plan = plan_gcps(polygon, AccuracyTarget(planimetric_rmse_m=0.05, vertical_rmse_m=0.10))
    assert plan.target_count >= 4
    assert len(plan.gcps) == plan.target_count
    assert any(g.role == "corner" for g in plan.gcps)


def test_plan_gcps_scales_with_area():
    big = np.array([[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]], dtype=np.float64)
    plan_small = plan_gcps(
        np.array([[0, 0], [50, 0], [50, 50], [0, 50], [0, 0]], dtype=np.float64),
        AccuracyTarget(0.05, 0.10),
    )
    plan_big = plan_gcps(big, AccuracyTarget(0.05, 0.10))
    assert plan_big.target_count >= plan_small.target_count


def test_plan_gcps_rejects_open_ring():
    with pytest.raises(ValueError):
        plan_gcps(np.array([[0, 0], [1, 0]], dtype=np.float64), AccuracyTarget(0.05, 0.10))


# ── mission ────────────────────────────────────────────────────────────────


def test_plan_grid_mission_emits_waypoints():
    config = MissionConfig(
        polygon_xy=((0, 0), (200, 0), (200, 100), (0, 100), (0, 0)),
        target_gsd_cm=2.5,
    )
    plan = plan_grid_mission(config)
    assert plan.altitude_m > 0
    assert plan.line_spacing_m > 0
    assert plan.photo_spacing_m > 0
    assert len(plan.waypoints) >= 4
    # All waypoints are at the same altitude.
    assert len({round(w.altitude_m, 3) for w in plan.waypoints}) == 1


def test_plan_grid_mission_to_json_round_trip():
    import json

    config = MissionConfig(
        polygon_xy=((0, 0), (100, 0), (100, 100), (0, 100), (0, 0)),
        target_gsd_cm=3.0,
    )
    plan = plan_grid_mission(config)
    payload = plan.to_json()
    parsed = json.loads(payload)
    assert "waypoints" in parsed
    assert parsed["altitude_m"] == pytest.approx(plan.altitude_m)
    assert len(parsed["waypoints"]) == len(plan.waypoints)
