"""Drone mission generator.

Given a polygon AOI + a desired ground sampling distance (GSD) + a
camera profile, computes:

* Flight altitude.
* Front and side overlap-tuned spacing.
* A boustrophedon (back-and-forth) waypoint pattern.
* Per-waypoint heading, speed, and gimbal pitch.

Outputs a JSON mission file that's the lingua franca of modern flight
planners (DJI Pilot 2, Wingtra Hub, Skydio Cloud all consume JSON
descendants of this shape). v0.2 will add native exporters for each
vendor.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class CameraProfile:
    name: str
    sensor_width_mm: float
    sensor_height_mm: float
    focal_length_mm: float
    image_width_px: int
    image_height_px: int

    @property
    def gsd_per_meter(self) -> float:
        """Ground-sampling-distance scale: cm at 1 m altitude."""
        # GSD = (sensor_width_mm * altitude_m) / (focal_length_mm * image_width_px)
        return (self.sensor_width_mm * 100.0) / (self.focal_length_mm * self.image_width_px)


@dataclass(frozen=True, slots=True)
class Aircraft:
    name: str
    cruise_speed_ms: float = 8.0
    max_speed_ms: float = 15.0
    battery_minutes: float = 25.0


@dataclass(frozen=True, slots=True)
class MissionConfig:
    """Inputs for :func:`plan_grid_mission`."""

    polygon_xy: tuple[tuple[float, float], ...]
    target_gsd_cm: float
    front_overlap_pct: float = 80.0
    side_overlap_pct: float = 70.0
    camera: CameraProfile = field(default=CameraProfile(
        name="DJI Phantom 4 RTK",
        sensor_width_mm=13.2,
        sensor_height_mm=8.8,
        focal_length_mm=8.8,
        image_width_px=5472,
        image_height_px=3648,
    ))
    aircraft: Aircraft = field(default=Aircraft(name="DJI P4 RTK"))
    home_xy: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class Waypoint:
    x: float
    y: float
    altitude_m: float
    heading_deg: float
    speed_ms: float
    gimbal_pitch_deg: float = -90.0
    take_photo: bool = True


@dataclass(frozen=True, slots=True)
class MissionPlan:
    config: MissionConfig
    altitude_m: float
    waypoints: tuple[Waypoint, ...]
    line_spacing_m: float
    photo_spacing_m: float
    estimated_minutes: float
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "altitude_m": self.altitude_m,
                "line_spacing_m": self.line_spacing_m,
                "photo_spacing_m": self.photo_spacing_m,
                "estimated_minutes": self.estimated_minutes,
                "notes": self.notes,
                "camera": asdict(self.config.camera),
                "aircraft": asdict(self.config.aircraft),
                "waypoints": [asdict(w) for w in self.waypoints],
            },
            indent=2,
        )

    def write(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")


def plan_grid_mission(config: MissionConfig) -> MissionPlan:
    """Generate a back-and-forth grid mission over the polygon."""
    polygon = np.asarray(config.polygon_xy, dtype=np.float64)
    if polygon.shape[0] < 3:
        raise ValueError("Polygon needs at least 3 vertices.")

    cam = config.camera
    # altitude_m so that GSD ≈ target_gsd_cm
    target_gsd_m_per_px = config.target_gsd_cm / 100.0
    altitude = (target_gsd_m_per_px * cam.focal_length_mm * cam.image_width_px) / cam.sensor_width_mm

    # Footprint at altitude (m)
    foot_w = (cam.sensor_width_mm * altitude) / cam.focal_length_mm
    foot_h = (cam.sensor_height_mm * altitude) / cam.focal_length_mm

    line_spacing = foot_w * (1 - config.side_overlap_pct / 100.0)
    photo_spacing = foot_h * (1 - config.front_overlap_pct / 100.0)

    # Grid orientation = longest polygon axis
    angle = _principal_axis_angle(polygon)
    rot = _rot(-angle)
    rot_back = _rot(angle)
    rotated = polygon @ rot.T
    min_xy = rotated.min(axis=0)
    max_xy = rotated.max(axis=0)
    rotated -= min_xy
    width = max_xy[0] - min_xy[0]
    height = max_xy[1] - min_xy[1]

    n_lines = max(2, math.ceil(width / line_spacing) + 1)
    waypoints: list[Waypoint] = []
    for i in range(n_lines):
        x = i * line_spacing
        # Snake direction
        ys = (
            np.arange(0, height + photo_spacing / 2, photo_spacing)
            if i % 2 == 0
            else np.arange(height, -photo_spacing / 2, -photo_spacing)
        )
        for y in ys:
            wp_local = np.array([x, y]) + min_xy
            wp_world = wp_local @ rot_back.T
            heading = math.degrees(angle) + (0.0 if i % 2 == 0 else 180.0)
            waypoints.append(
                Waypoint(
                    x=float(wp_world[0]),
                    y=float(wp_world[1]),
                    altitude_m=float(altitude),
                    heading_deg=heading % 360,
                    speed_ms=config.aircraft.cruise_speed_ms,
                )
            )

    distance = sum(
        math.hypot(b.x - a.x, b.y - a.y)
        for a, b in itertools.pairwise(waypoints)
    )
    minutes = distance / max(config.aircraft.cruise_speed_ms, 0.1) / 60 + 2.0

    notes = (
        f"GSD={config.target_gsd_cm:.2f} cm @ {altitude:.1f} m AGL; "
        f"footprint {foot_w:.1f}×{foot_h:.1f} m; "
        f"front/side overlap {config.front_overlap_pct:.0f}/{config.side_overlap_pct:.0f}%; "
        f"{n_lines} lines, {len(waypoints)} waypoints."
    )
    return MissionPlan(
        config=config,
        altitude_m=float(altitude),
        waypoints=tuple(waypoints),
        line_spacing_m=float(line_spacing),
        photo_spacing_m=float(photo_spacing),
        estimated_minutes=float(minutes),
        notes=notes,
    )


# ── helpers ─────────────────────────────────────────────────────────────────


def _rot(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]], dtype=np.float64)


def _principal_axis_angle(polygon: np.ndarray) -> float:
    """Angle of the polygon's principal axis (radians)."""
    centred = polygon - polygon.mean(axis=0)
    cov = np.cov(centred.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    major = eigvecs[:, np.argmax(eigvals)]
    return float(math.atan2(major[1], major[0]))
