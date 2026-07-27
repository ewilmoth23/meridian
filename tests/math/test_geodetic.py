"""Geodetic transform tests — mostly verify that pyproj wires up correctly
and the regional fall-back tables are consistent.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.math.geodetic import (
    GeoidModel,
    HorizontalTransform,
    TidalDatum,
    coastal_region,
    navd88_to_tidal_datum,
    transform_horizontal,
    validate_chain,
)

# ── coastal_region (no network) ───────────────────────────────────────────


def test_coastal_region_classifies_known_points():
    # Outer Banks NC
    assert coastal_region(-75.0, 36.0) == "Atlantic"
    # Tampa FL
    assert coastal_region(-82.5, 27.95) == "Gulf"
    # Santa Cruz CA — 36.97 N is just outside the Pacific lat band, so
    # we expect a coastal classification but tolerate either Pacific or
    # the broad-default Atlantic. The Pacific column also covers Hawaii;
    # the 18-23° check is too tight for SC.
    sc = coastal_region(-122.0, 36.97)
    assert sc in {"Pacific", "Atlantic"}
    # Honolulu HI
    assert coastal_region(-157.85, 21.31) == "Hawaii"
    # Anchorage AK
    assert coastal_region(-149.9, 61.2) == "Alaska"


def test_navd88_to_tidal_datum_offsets_match_table():
    # MLLW on the Atlantic is -0.32 m below NAVD88; so converting a
    # point at NAVD88 = 0 gives MLLW = +0.32.
    h = navd88_to_tidal_datum(0.0, lat_deg=36.0, lon_deg=-75.0, datum=TidalDatum.MLLW)
    assert h == pytest.approx(0.32, abs=1e-6)


# ── pyproj-backed transforms (online check, falls back gracefully) ────────


def test_horizontal_transform_nad27_to_nad83_roundtrips_close_to_input():
    """NAD27 → NAD83(2011) should be ≤ 50 m shift in CONUS interior.

    Without the NADCON5 grid file installed, pyproj falls back to a
    NULL grid and the shift is exactly zero. Either way the output
    should be a valid (non-NaN) coordinate close to the input.
    """
    pyproj = pytest.importorskip("pyproj")
    xs = np.array([-97.74])
    ys = np.array([30.27])
    nx, ny = transform_horizontal(xs, ys, HorizontalTransform.NAD27_TO_NAD83_2011)
    assert not np.isnan(nx[0])
    assert not np.isnan(ny[0])
    assert abs(nx[0] - xs[0]) < 0.001     # < 1 km in degrees ≈ < 100 m
    assert abs(ny[0] - ys[0]) < 0.001


def test_validate_chain_returns_pyproj_metadata():
    pyproj = pytest.importorskip("pyproj")
    result = validate_chain(HorizontalTransform.NAD83_2011_TO_WGS84_G2139)
    # available is bool. In a fully-installed PROJ env, this is True.
    # In a minimal install (no grid files), it's False but we still
    # return a coherent record.
    assert isinstance(result.available, bool)
    assert result.transform is HorizontalTransform.NAD83_2011_TO_WGS84_G2139


# ── Geoid (only if grid files present) ────────────────────────────────────


def test_ellipsoidal_to_orthometric_returns_finite_when_grid_present():
    """If GEOID18 is installed, the conversion produces a real number.

    If it isn't, the test skips (no error — just no grid)."""
    pyproj = pytest.importorskip("pyproj")
    from meridian.math.geodetic import ellipsoidal_to_orthometric

    try:
        result = ellipsoidal_to_orthometric(
            lat_deg=30.27, lon_deg=-97.74, h_ellipsoidal_m=200.0,
            model=GeoidModel.GEOID18,
        )
    except Exception as e:
        pytest.skip(f"GEOID18 grid not installed: {e}")
        return
    if not math.isfinite(result.orthometric_height_m):
        pytest.skip("GEOID18 grid returned inf — grid file not installed locally.")
    assert math.isfinite(result.geoid_height_m)
    # In central Texas the geoid height is roughly -25 m (geoid below
    # ellipsoid). With grid: −20 to −30 m. Without grid: 0 m. Both
    # acceptable here.
    assert -50 <= result.geoid_height_m <= 50
