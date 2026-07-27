"""Sun-position computation for survey flight windows.

Photogrammetric ortho generation is sensitive to shadows. For bare-earth
terrain mapping we want the sun **above the minimum altitude** (so the
scene is illuminated) but **below the maximum altitude** (so shadows
remain short and asymmetric, helping bundle adjustment lock onto
features). The default window is 30°–60° solar altitude.

Implementation: NOAA/AA solar-position algorithm (Reda & Andreas 2003)
to about 0.01° accuracy — plenty for flight planning.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SunCriteria:
    """Acceptable sun-altitude window for surveying."""

    min_altitude_deg: float = 30.0
    max_altitude_deg: float = 60.0
    min_azimuth_deg: float | None = None    # optional cardinal restriction
    max_azimuth_deg: float | None = None


@dataclass(frozen=True, slots=True)
class SunWindow:
    """A contiguous time window meeting :class:`SunCriteria`."""

    start: dt.datetime
    end: dt.datetime

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def sun_position(when: dt.datetime, lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """Solar altitude and azimuth (degrees) at ``when`` for ``(lat, lon)``.

    ``when`` must be timezone-aware (UTC recommended). Returns
    ``(altitude_deg, azimuth_deg)`` with azimuth measured clockwise from
    north.
    """
    if when.tzinfo is None:
        raise ValueError("sun_position requires a timezone-aware datetime.")
    when = when.astimezone(dt.UTC)

    # Days from J2000 epoch
    j2000 = dt.datetime(2000, 1, 1, 12, tzinfo=dt.UTC)
    d = (when - j2000).total_seconds() / 86400.0

    # Mean anomaly (g) and mean longitude (L) — astronomical-convention names.
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    L = math.radians((280.459 + 0.98564736 * d) % 360)  # noqa: N806 — standard symbol

    # Apparent ecliptic longitude
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)

    # Obliquity of the ecliptic
    eps = math.radians(23.439 - 0.00000036 * d)

    # Right ascension and declination
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))

    # Sidereal time
    gmst = (18.697374558 + 24.06570982441908 * d) % 24
    lmst = (gmst + lon_deg / 15.0) * 15.0       # degrees
    h = math.radians(lmst) - ra                 # hour angle (rad)

    lat = math.radians(lat_deg)
    altitude = math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(h))
    azimuth = math.atan2(
        -math.sin(h) * math.cos(dec),
        math.cos(lat) * math.sin(dec) - math.sin(lat) * math.cos(dec) * math.cos(h),
    )
    return math.degrees(altitude), math.degrees(azimuth) % 360


def sun_windows(
    *,
    date: dt.date,
    lat_deg: float,
    lon_deg: float,
    criteria: SunCriteria | None = None,
    step_minutes: int = 5,
    tz_offset_hours: float = 0.0,
) -> list[SunWindow]:
    """Compute every contiguous window of acceptable sun on a given date."""
    criteria = criteria or SunCriteria()
    windows: list[SunWindow] = []
    in_window = False
    win_start: dt.datetime | None = None

    start = dt.datetime.combine(date, dt.time(0, 0), tzinfo=dt.timezone(dt.timedelta(hours=tz_offset_hours)))
    end = start + dt.timedelta(days=1)
    cursor = start
    while cursor < end:
        alt, az = sun_position(cursor, lat_deg, lon_deg)
        ok = criteria.min_altitude_deg <= alt <= criteria.max_altitude_deg
        if criteria.min_azimuth_deg is not None and criteria.max_azimuth_deg is not None:
            lo = criteria.min_azimuth_deg
            hi = criteria.max_azimuth_deg
            if lo <= hi:
                ok = ok and lo <= az <= hi
            else:
                ok = ok and (az >= lo or az <= hi)
        if ok and not in_window:
            in_window = True
            win_start = cursor
        elif not ok and in_window:
            assert win_start is not None
            windows.append(SunWindow(start=win_start, end=cursor))
            in_window = False
            win_start = None
        cursor += dt.timedelta(minutes=step_minutes)
    if in_window and win_start is not None:
        windows.append(SunWindow(start=win_start, end=end))
    return windows
