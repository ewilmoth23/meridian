"""Tax-parcel cross-reference tests (offline, mocked provider)."""

from __future__ import annotations

import pytest

from meridian.domain.crs import WGS84
from meridian.domain.geometry import Point2D, Polygon
from meridian.domain.parcel import Boundary, Parcel
from meridian.jurisdictions.tax_parcel import (
    COUNTY_SERVICES,
    InMemoryProvider,
    TaxParcel,
    cross_check,
    get_county,
    list_counties,
    register_county,
)


def _build_surveyed():
    pts = (
        Point2D(-97.7444, 30.2672, WGS84),
        Point2D(-97.7434, 30.2672, WGS84),
        Point2D(-97.7434, 30.2682, WGS84),
        Point2D(-97.7444, 30.2682, WGS84),
        Point2D(-97.7444, 30.2672, WGS84),
    )
    poly = Polygon(exterior=pts).oriented()
    return Parcel(
        name="Surveyed",
        crs=WGS84,
        calls=(),
        boundary=Boundary(
            polygon=poly, misclosure_distance=0.0, misclosure_bearing=0.0,
            perimeter=poly.perimeter(), closure_ratio=float("inf"),
            point_of_beginning=pts[0],
        ),
    )


def test_county_registry_has_seeded_counties():
    assert "TX_TRAVIS" in COUNTY_SERVICES
    assert "CA_LOS_ANGELES" in COUNTY_SERVICES
    assert get_county("TX_TRAVIS").state == "TX"


def test_register_county_adds_to_registry():
    from meridian.jurisdictions.tax_parcel import CountyService
    register_county(
        "TEST_DUMMY",
        CountyService(state="ZZ", county="Dummy", base_url="https://example.com/foo"),
    )
    assert "TEST_DUMMY" in COUNTY_SERVICES
    assert any(c.county == "Dummy" for c in list_counties())


def test_in_memory_provider_returns_canned_record():
    provider = InMemoryProvider()
    record = TaxParcel(
        apn="R12345",
        owner="John Doe",
        address="100 Main St",
        acreage=1.0,
        geometry_wgs84=((-97.74, 30.26), (-97.73, 30.26), (-97.73, 30.27), (-97.74, 30.27), (-97.74, 30.26)),
        state="TX", county="Travis",
    )
    provider.parcels_by_apn["R12345"] = record
    fetched = provider.get_by_apn(get_county("TX_TRAVIS"), "R12345")
    assert fetched is not None
    assert fetched.owner == "John Doe"


def test_cross_check_passes_when_polygons_match():
    surv = _build_surveyed()
    tax = TaxParcel(
        apn="R12345",
        owner="John Doe",
        address=None,
        acreage=None,
        geometry_wgs84=tuple((p.x, p.y) for p in surv.boundary.polygon.exterior),
        state="TX", county="Travis",
    )
    result = cross_check(surv, tax)
    assert result.pass_match is True
    assert result.area_ratio == pytest.approx(1.0, abs=1e-6)
    assert result.hausdorff_m == pytest.approx(0.0, abs=1e-6)


def test_cross_check_fails_for_offset_polygons():
    surv = _build_surveyed()
    # Shift assessor record by ~100 m east — way outside tolerance.
    tax = TaxParcel(
        apn="R12345",
        owner="John Doe",
        address=None,
        acreage=None,
        geometry_wgs84=tuple(
            (p.x + 0.001, p.y) for p in surv.boundary.polygon.exterior
        ),
        state="TX", county="Travis",
    )
    result = cross_check(surv, tax)
    assert result.pass_match is False
    assert result.notes


def test_cross_check_rejects_unbounded_parcel():
    surv = Parcel(name="x", crs=WGS84, calls=())
    tax = TaxParcel(
        apn="R", owner=None, address=None, acreage=None,
        geometry_wgs84=((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)),
        state="TX", county="Travis",
    )
    with pytest.raises(ValueError, match="no boundary"):
        cross_check(surv, tax)
