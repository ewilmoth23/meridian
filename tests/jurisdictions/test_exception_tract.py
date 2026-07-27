"""LESS-AND-EXCEPT / multi-tract deed parser tests."""

from __future__ import annotations

import pytest

from meridian.domain.crs import CRS
from meridian.domain.geometry import Point2D
from meridian.jurisdictions.exception_tract import (
    TractRole,
    compute_net_area,
    detect_exceptions,
    detect_multi_tract,
    parse_multi_tract_document,
)

SQUARE_400 = (
    "BEGINNING at the POB; "
    "thence N 0°00'00\" E a distance of 100.000 meters; "
    "thence N 90°00'00\" E a distance of 100.000 meters; "
    "thence S 0°00'00\" W a distance of 100.000 meters; "
    "thence S 90°00'00\" W a distance of 100.000 meters to the POB."
)

SQUARE_100 = (
    "BEGINNING at the POB; "
    "thence N 0°00'00\" E a distance of 50.000 meters; "
    "thence N 90°00'00\" E a distance of 50.000 meters; "
    "thence S 0°00'00\" W a distance of 50.000 meters; "
    "thence S 90°00'00\" W a distance of 50.000 meters to the POB."
)


def test_detect_exception_clauses():
    assert detect_exceptions("Beginning... SAVE AND EXCEPT that portion described as...")
    assert detect_exceptions("...LESS AND EXCEPTING the railroad ROW...")
    assert detect_exceptions("Reserving unto the grantor a 5-acre tract...")
    assert not detect_exceptions("Plain old metes and bounds with no carve-out.")


def test_detect_multi_tract():
    assert detect_multi_tract("Tract 1: described as...\nTract 2: described as...")
    assert detect_multi_tract("Parcel A.\nThe following described land...\nParcel B.")
    assert not detect_multi_tract("Lot 5 of the Sunset subdivision")


def test_parse_save_and_except_produces_parent_and_exception():
    text = SQUARE_400 + " SAVE AND EXCEPT that portion described as: " + SQUARE_100
    doc = parse_multi_tract_document(text)
    assert doc.parent.role is TractRole.PARENT
    assert len(doc.exceptions) == 1
    assert doc.exceptions[0].role is TractRole.EXCEPTION


def test_compute_net_area_subtracts_exception():
    text = SQUARE_400 + " SAVE AND EXCEPT that portion described as: " + SQUARE_100
    doc = parse_multi_tract_document(text)
    pob = Point2D(0.0, 0.0, CRS(epsg=2277))
    result = compute_net_area(doc, pob.crs, pob=pob)
    # 400m² × 400m² = 10000 m². Subtract 50×50 = 2500 m² → 7500 m² net.
    # (100m × 100m parent = 10000; 50m × 50m exception = 2500; net = 7500.)
    assert result.parent_area_m2 == pytest.approx(10000.0, abs=1.0)
    assert result.exception_area_m2 == pytest.approx(2500.0, abs=1.0)
    assert result.net_area_m2 == pytest.approx(7500.0, abs=1.0)
    assert result.method == "exact"


def test_multi_tract_with_explicit_headers():
    text = (
        "Tract 1: " + SQUARE_400 + "\n"
        "Tract 2: " + SQUARE_100
    )
    doc = parse_multi_tract_document(text)
    assert doc.parent.label == "Tract 1"
    assert len(doc.additional_tracts) == 1
    assert doc.additional_tracts[0].label == "Tract 2"


def test_reservation_clause_captured():
    text = SQUARE_400 + " RESERVING UNTO the grantor all mineral rights below 100 feet."
    doc = parse_multi_tract_document(text)
    assert len(doc.reservations) == 1
    assert "mineral rights" in doc.reservations[0].text.lower()
