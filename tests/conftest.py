"""Shared pytest fixtures for the Meridian test suite."""

from __future__ import annotations

import pytest


@pytest.fixture()
def crs_local():
    """Return a synthetic EPSG-less local CRS for math tests.

    Uses EPSG:4326 as a stand-in so :class:`CRS` validation passes; tests
    that exercise the math don't actually transform anything.
    """
    from meridian.domain.crs import CRS, Datum, HorizontalAxis, LinearUnit
    return CRS(
        epsg=4326,
        datum=Datum(name="WGS 84", epsg=6326),
        horizontal_axis=HorizontalAxis.LAT_LON,
        units=LinearUnit.METER,
    )


@pytest.fixture()
def texas_central_crs():
    """Texas State Plane Central NAD83(2011) US ft — common deed CRS."""
    from meridian.domain.crs import CRS, Datum, LinearUnit, Projection
    return CRS(
        epsg=2277,
        datum=Datum(name="NAD83", realization="2011", epsg=6318),
        projection=Projection(name="Texas Central", epsg=2277, units=LinearUnit.US_SURVEY_FOOT),
        units=LinearUnit.US_SURVEY_FOOT,
    )


@pytest.fixture()
def square_calls_text():
    """A perfect 100m square deed. Should close to <1 mm."""
    return (
        "Beginning at the Point of Beginning; "
        "thence N 0°00'00\" E a distance of 100 meters; "
        "thence N 90°00'00\" E a distance of 100 meters; "
        "thence S 0°00'00\" W a distance of 100 meters; "
        "thence S 90°00'00\" W a distance of 100 meters "
        "to the Point of Beginning."
    )
