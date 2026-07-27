"""Tax-parcel cross-reference.

County assessors expose their parcel layers via ArcGIS REST endpoints
(roughly 70% of US counties as of 2026). Given an APN or a coordinate,
this module:

1. Queries the appropriate county service.
2. Returns the assessor's geometry + ownership / valuation attributes.
3. Cross-checks against a surveyed boundary (Hausdorff distance + per-
   vertex deviation) to flag where the assessor's record disagrees with
   the surveyor's boundary.

The query layer is provider-agnostic (``ArcGISRESTProvider`` is the only
implementation today; FL DOR's GeoJSON service and the WFS counties get
a pass-through). Network requests live behind an :class:`ArcGISRESTProvider`
class that's mockable so tests stay offline.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlencode

import numpy as np

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.parcel import Parcel


# ── Service registry ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CountyService:
    """One county's assessor REST endpoint."""

    state: str
    county: str
    base_url: str
    apn_field: str = "APN"
    owner_field: str = "OWNER"
    address_field: str = "SITUS_ADDR"
    acreage_field: str = "ACRES"
    crs_epsg: int = 4326
    notes: str | None = None


# Pre-populated registry of major counties (all real public endpoints).
# This is the seed; users add more via :func:`register_county`.
COUNTY_SERVICES: dict[str, CountyService] = {
    "TX_TRAVIS": CountyService(
        state="TX", county="Travis",
        base_url="https://gis.tcad.org/arcgis/rest/services/Public/TCAD_Properties/MapServer/0",
        apn_field="PROP_ID", owner_field="OWNER_NAME", address_field="SITUS_ADDR",
        acreage_field="LEGAL_ACREAGE", crs_epsg=4326,
    ),
    "TX_HARRIS": CountyService(
        state="TX", county="Harris",
        base_url="https://gis.hcad.org/arcgis/rest/services/public/Parcels/MapServer/0",
        apn_field="HCAD_NUM", owner_field="MAILING_NAME", crs_epsg=4326,
    ),
    "CA_LOS_ANGELES": CountyService(
        state="CA", county="Los Angeles",
        base_url="https://maps.assessor.lacounty.gov/arcgis/rest/services/Public/Parcel/MapServer/0",
        apn_field="AIN", owner_field="SitusOwner", crs_epsg=2229,
    ),
    "FL_MIAMI_DADE": CountyService(
        state="FL", county="Miami-Dade",
        base_url="https://gisweb.miamidade.gov/arcgis/rest/services/Property/Property/MapServer/0",
        apn_field="FOLIO", owner_field="OWNER1", crs_epsg=2236,
    ),
    "WA_KING": CountyService(
        state="WA", county="King",
        base_url="https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_GIS_Parcel/MapServer/0",
        apn_field="PIN", owner_field="TAXPAYER", crs_epsg=2926,
    ),
    "AZ_MARICOPA": CountyService(
        state="AZ", county="Maricopa",
        base_url="https://gis.mcassessor.maricopa.gov/arcgis/rest/services/Public/MapServer/0",
        apn_field="APN", owner_field="OwnerName", crs_epsg=2868,
    ),
    "GA_FULTON": CountyService(
        state="GA", county="Fulton",
        base_url="https://gisarcgis.fultoncountyga.gov/arcgis/rest/services/Public/Parcels/MapServer/0",
        apn_field="PARCELID", owner_field="OWNER1",
    ),
    "NY_NYC": CountyService(
        state="NY", county="New York City",
        base_url="https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/ArcGIS/rest/services/MAPPLUTO/FeatureServer/0",
        apn_field="BBL", owner_field="OWNERNAME",
    ),
    "OH_FRANKLIN": CountyService(
        state="OH", county="Franklin",
        base_url="https://maps.franklincountyauditor.com/arcgis/rest/services/Maps/Parcels/MapServer/0",
        apn_field="PARCELID", owner_field="OWNER",
    ),
    "CO_DENVER": CountyService(
        state="CO", county="Denver",
        base_url="https://services3.arcgis.com/iSXIxXRgWQ75QSpx/ArcGIS/rest/services/parcels/FeatureServer/0",
        apn_field="SCHEDNUM", owner_field="OWNER_NAME",
    ),
}


def register_county(key: str, service: CountyService) -> None:
    """Add a county to the registry. Useful for jurisdictions we don't ship."""
    COUNTY_SERVICES[key] = service


def get_county(key: str) -> CountyService:
    if key not in COUNTY_SERVICES:
        raise KeyError(f"Unknown county: {key!r}. Known: {sorted(COUNTY_SERVICES)}")
    return COUNTY_SERVICES[key]


def list_counties() -> list[CountyService]:
    return list(COUNTY_SERVICES.values())


# ── Tax-parcel record ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TaxParcel:
    """One assessor record."""

    apn: str
    owner: str | None
    address: str | None
    acreage: float | None
    geometry_wgs84: tuple[tuple[float, float], ...]    # exterior ring (lon, lat)
    state: str
    county: str
    raw_attributes: dict[str, object] = field(default_factory=dict)
    valuation: float | None = None
    legal_description: str | None = None


# ── Provider protocol ────────────────────────────────────────────────────


class TaxParcelProvider(Protocol):
    """Interface for any backend that can fetch tax-parcel records."""

    def get_by_apn(self, county: CountyService, apn: str) -> TaxParcel | None: ...

    def query_at(self, county: CountyService, lon: float, lat: float) -> TaxParcel | None: ...


# ── ArcGIS REST provider ─────────────────────────────────────────────────


@dataclass(slots=True)
class ArcGISRESTProvider:
    """Real ArcGIS REST query implementation. Cached in-memory.

    Tests should pass an :class:`InMemoryProvider` instead.
    """

    timeout_s: float = 15.0
    _cache: dict[str, TaxParcel] = field(default_factory=dict)

    def get_by_apn(self, county: CountyService, apn: str) -> TaxParcel | None:
        cache_key = f"{county.state}_{county.county}|apn|{apn}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        params = {
            "where": f"{county.apn_field} = '{apn}'",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "json",
        }
        body = self._fetch(f"{county.base_url}/query?{urlencode(params)}")
        parcel = _build_parcel_from_arcgis(body, county)
        if parcel is not None:
            self._cache[cache_key] = parcel
        return parcel

    def query_at(self, county: CountyService, lon: float, lat: float) -> TaxParcel | None:
        cache_key = f"{county.state}_{county.county}|xy|{lon:.6f}_{lat:.6f}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        # Use ArcGIS's geometry envelope query.
        env = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})
        params = {
            "geometry": env,
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "json",
        }
        body = self._fetch(f"{county.base_url}/query?{urlencode(params)}")
        parcel = _build_parcel_from_arcgis(body, county)
        if parcel is not None:
            self._cache[cache_key] = parcel
        return parcel

    def _fetch(self, url: str) -> dict[str, object]:
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("requests is required") from e
        r = requests.get(url, timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()


def _build_parcel_from_arcgis(body: dict[str, object], county: CountyService) -> TaxParcel | None:
    features = body.get("features") or []
    if not features:
        return None
    feat = features[0]
    attrs = feat.get("attributes") or {}
    geom = feat.get("geometry") or {}
    rings = geom.get("rings") or []
    if not rings:
        return None
    ring = rings[0]
    return TaxParcel(
        apn=str(attrs.get(county.apn_field, "")),
        owner=str(attrs.get(county.owner_field) or "") or None,
        address=str(attrs.get(county.address_field) or "") or None,
        acreage=float(attrs.get(county.acreage_field) or 0) or None,
        geometry_wgs84=tuple((float(p[0]), float(p[1])) for p in ring),
        state=county.state,
        county=county.county,
        raw_attributes=dict(attrs),
    )


# ── In-memory provider (testing) ─────────────────────────────────────────


@dataclass(slots=True)
class InMemoryProvider:
    """Test-friendly provider that serves canned :class:`TaxParcel` records."""

    parcels_by_apn: dict[str, TaxParcel] = field(default_factory=dict)
    parcels_at_xy: dict[tuple[float, float], TaxParcel] = field(default_factory=dict)

    def get_by_apn(self, county: CountyService, apn: str) -> TaxParcel | None:
        return self.parcels_by_apn.get(apn)

    def query_at(self, county: CountyService, lon: float, lat: float) -> TaxParcel | None:
        return self.parcels_at_xy.get((round(lon, 6), round(lat, 6)))


# ── Cross-check ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TaxParcelCrossCheck:
    """How well a surveyed boundary matches the assessor record."""

    apn: str
    surveyed_area_m2: float
    assessor_area_m2: float
    area_ratio: float                  # surveyed / assessor (1.0 = match)
    hausdorff_m: float                  # symmetric Hausdorff distance
    max_vertex_offset_m: float
    pass_match: bool                    # True if both metrics within tolerance
    notes: tuple[str, ...] = ()


def cross_check(
    surveyed: Parcel,
    tax_parcel: TaxParcel,
    *,
    target_crs: CRS | None = None,
    area_tolerance_pct: float = 5.0,
    hausdorff_tolerance_m: float = 5.0,
) -> TaxParcelCrossCheck:
    """Compare a surveyed parcel against an assessor record.

    Both polygons are reprojected to ``target_crs`` (or the surveyed
    parcel's CRS if not supplied) before comparison so units match.
    """
    from meridian.domain.crs import WGS84
    from meridian.math.statistics import hausdorff_distance
    from meridian.math.transforms import transform_xy

    if surveyed.boundary is None:
        raise ValueError(f"Surveyed parcel {surveyed.name!r} has no boundary.")

    # Pick a metric target CRS so Hausdorff and area come out in real meters.
    # If the caller didn't supply one and the surveyed parcel is geographic
    # (lat/lon), we auto-pick a UTM zone from the centroid.
    target = target_crs or surveyed.crs
    if target.is_geographic():
        target = _auto_utm_for(surveyed.boundary.polygon.exterior)
    surv_pts = surveyed.boundary.polygon.exterior
    surv_xy = _ring_to_xy(surv_pts)
    if surveyed.crs != target:
        sx, sy = transform_xy(surv_xy[:, 0], surv_xy[:, 1], surveyed.crs, target)
        surv_xy = _stack(sx, sy)

    tax_xy = _ring_to_xy_tuples(tax_parcel.geometry_wgs84)
    if target != WGS84:
        tx, ty = transform_xy(tax_xy[:, 0], tax_xy[:, 1], WGS84, target)
        tax_xy = _stack(tx, ty)

    surv_area = _shoelace_area(surv_xy)
    assr_area = _shoelace_area(tax_xy)
    ratio = surv_area / assr_area if assr_area > 0 else 0.0
    h = float(hausdorff_distance(surv_xy, tax_xy))

    # Per-vertex closest-point offset for the surveyed ring.
    offsets = []
    for x, y in surv_xy:
        d = ((tax_xy[:, 0] - x) ** 2 + (tax_xy[:, 1] - y) ** 2) ** 0.5
        offsets.append(float(d.min()))
    max_offset = max(offsets) if offsets else 0.0

    notes: list[str] = []
    pass_area = abs(ratio - 1.0) <= (area_tolerance_pct / 100.0)
    if not pass_area:
        notes.append(f"Area differs by {abs(ratio - 1.0) * 100:.2f}%")
    if h > hausdorff_tolerance_m:
        notes.append(f"Hausdorff {h:.2f} m exceeds {hausdorff_tolerance_m:.2f} m tolerance")

    return TaxParcelCrossCheck(
        apn=tax_parcel.apn,
        surveyed_area_m2=surv_area,
        assessor_area_m2=assr_area,
        area_ratio=ratio,
        hausdorff_m=h,
        max_vertex_offset_m=max_offset,
        pass_match=pass_area and h <= hausdorff_tolerance_m,
        notes=tuple(notes),
    )


# ── helpers ────────────────────────────────────────────────────────────────


def _ring_to_xy(pts) -> np.ndarray:
    return np.array([[p.x, p.y] for p in pts], dtype=np.float64)


def _ring_to_xy_tuples(pts: Iterable[tuple[float, float]]) -> np.ndarray:
    arr = np.array(list(pts), dtype=np.float64)
    if arr.size == 0:
        return arr
    if not (arr[0, 0] == arr[-1, 0] and arr[0, 1] == arr[-1, 1]):
        arr = np.vstack([arr, arr[0]])
    return arr


def _stack(xs, ys) -> np.ndarray:
    return np.column_stack([xs, ys])


def _shoelace_area(coords) -> float:
    if coords.shape[0] < 3:
        return 0.0
    cx = float(coords[:-1, 0].mean())
    cy = float(coords[:-1, 1].mean())
    x = coords[:, 0] - cx
    y = coords[:, 1] - cy
    return abs(0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])))


def _auto_utm_for(ring) -> CRS:
    """Auto-pick a UTM zone from a lon/lat ring's centroid.

    Used by :func:`cross_check` when both the surveyed parcel and the
    assessor record are in WGS84 — Hausdorff distance and area only
    make sense in a metric CRS.
    """
    from meridian.domain.crs import utm

    lons = [p.x for p in ring]
    lats = [p.y for p in ring]
    cx = sum(lons) / len(lons)
    cy = sum(lats) / len(lats)
    zone = int((cx + 180) / 6) + 1
    hemisphere = "N" if cy >= 0 else "S"
    return utm(zone, hemisphere, datum="WGS84")
