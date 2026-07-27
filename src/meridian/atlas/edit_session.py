"""In-memory editable fabric backing the Atlas interactive viewer.

When the Atlas viewer runs in *demo mode* (no project DB attached) — and
also as the staging area for edits before they're persisted to the project
DB — the viewer needs somewhere to put new parcels, mutated parcels, and
in-flight measurements. That place is :class:`EditSession`.

An :class:`EditSession` wraps a :class:`~meridian.jurisdictions.fabric.ParcelFabric`
in a thread-safe, JSON-friendly façade and emits stable string IDs the
viewer can refer to. It deliberately speaks WGS84 (EPSG:4326) lon/lat —
Cesium hands us cartographic coordinates, and we don't want to push CRS
selection into the wire format.

This is *not* a replacement for the project DB. Long-term storage goes
through :mod:`meridian.adapters.persistence`. The session is the v0.4
"draw a thing on the globe and have it persist within this run" layer.
"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from meridian.domain.crs import CRS, Datum, HorizontalAxis, LinearUnit
from meridian.domain.geometry import Point2D, Polygon
from meridian.jurisdictions.fabric import ParcelFabric

# Shared geographic CRS used by the viewer. Cesium gives us cartographic
# coordinates; we store them in this CRS and let downstream tools project
# as needed.
_VIEWER_CRS = CRS(
    epsg=4326,
    datum=Datum(name="WGS 84", realization="G2139", epsg=6326),
    horizontal_axis=HorizontalAxis.LON_LAT,
    units=LinearUnit.METER,
)


@dataclass(frozen=True, slots=True)
class ParcelMetadata:
    """Free-form attributes attached to a session parcel."""

    name: str = ""
    description: str = ""
    owner: str = ""
    apn: str = ""
    color: str = "#ffd76e"
    tags: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "apn": self.apn,
            "color": self.color,
            "tags": list(self.tags),
            "extra": dict(self.extra),
        }


def _meta_from_props(props: dict[str, Any] | None) -> ParcelMetadata:
    props = props or {}
    return ParcelMetadata(
        name=str(props.get("name", "")),
        description=str(props.get("description", "")),
        owner=str(props.get("owner", "")),
        apn=str(props.get("apn", "")),
        color=str(props.get("color", "#ffd76e")) or "#ffd76e",
        tags=tuple(str(t) for t in (props.get("tags") or ())),
        extra={k: str(v) for k, v in (props.get("extra") or {}).items()},
    )


class EditSession:
    """A live, editable scene of parcels + annotations.

    All mutation methods are synchronised. The session keeps both a
    :class:`ParcelFabric` (for topology / shared edges / merges / splits)
    and a side-table of per-parcel metadata.
    """

    def __init__(self, *, snap_tolerance_m: float = 0.10) -> None:
        # Snap tolerance is given in metres; the fabric stores degrees, so
        # we keep both — the fabric uses an effective degree tolerance, and
        # the session converts at insertion time.
        self._tol_m = snap_tolerance_m
        self._fabric = ParcelFabric(snap_tolerance=self._meters_to_degrees(snap_tolerance_m))
        self._meta: dict[str, ParcelMetadata] = {}
        self._lock = threading.RLock()

    # ── Conversion helpers ─────────────────────────────────────────────────

    @staticmethod
    def _meters_to_degrees(m: float) -> float:
        # 1 degree of latitude ≈ 111_000 m. We use this as a uniform
        # tolerance — slight over-snap near the equator, slight under-snap
        # near the poles, but for the metre-scale tolerances we care about
        # (≤1 m) the error is negligible.
        return m / 111_000.0

    def _ring_to_points(self, ring: list[list[float]]) -> list[Point2D]:
        out: list[Point2D] = []
        for c in ring:
            if len(c) < 2:
                raise ValueError("Each ring coordinate must be [lon, lat] (or [lon, lat, h]).")
            out.append(Point2D(x=float(c[0]), y=float(c[1]), crs=_VIEWER_CRS))
        return out

    @staticmethod
    def _polygon_to_ring(poly: Polygon) -> list[list[float]]:
        return [[p.x, p.y] for p in poly.exterior]

    # ── CRUD ───────────────────────────────────────────────────────────────

    def list_parcels(self) -> list[dict[str, Any]]:
        """Return every parcel as a GeoJSON-friendly dict."""
        with self._lock:
            return [self._dump_parcel(p.id) for p in self._fabric.parcels()]

    def get_parcel(self, parcel_id: str) -> dict[str, Any]:
        with self._lock:
            return self._dump_parcel(parcel_id)

    def create_parcel(
        self, ring: list[list[float]], properties: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            parcel_id = self._next_id()
            meta = _meta_from_props(properties)
            self._fabric.add_parcel_from_ring(parcel_id, meta.name or parcel_id, self._ring_to_points(ring))
            self._meta[parcel_id] = meta
            return self._dump_parcel(parcel_id)

    def update_parcel_geometry(
        self, parcel_id: str, ring: list[list[float]]
    ) -> dict[str, Any]:
        with self._lock:
            if parcel_id not in self._fabric:
                raise KeyError(parcel_id)
            old_meta = self._meta.get(parcel_id, ParcelMetadata())
            self._fabric.remove_parcel(parcel_id)
            self._fabric.add_parcel_from_ring(parcel_id, old_meta.name or parcel_id, self._ring_to_points(ring))
            self._meta[parcel_id] = old_meta
            return self._dump_parcel(parcel_id)

    def update_parcel_properties(
        self, parcel_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            if parcel_id not in self._fabric:
                raise KeyError(parcel_id)
            existing = self._meta.get(parcel_id, ParcelMetadata())
            merged = ParcelMetadata(
                name=str(properties.get("name", existing.name)),
                description=str(properties.get("description", existing.description)),
                owner=str(properties.get("owner", existing.owner)),
                apn=str(properties.get("apn", existing.apn)),
                color=str(properties.get("color", existing.color)) or existing.color,
                tags=tuple(properties["tags"]) if "tags" in properties else existing.tags,
                extra={**existing.extra, **(properties.get("extra") or {})},
            )
            self._meta[parcel_id] = merged
            return self._dump_parcel(parcel_id)

    def delete_parcel(self, parcel_id: str) -> None:
        with self._lock:
            if parcel_id not in self._fabric:
                raise KeyError(parcel_id)
            self._fabric.remove_parcel(parcel_id)
            self._meta.pop(parcel_id, None)

    def split_parcel(
        self,
        parcel_id: str,
        cut: tuple[list[float], list[float]],
        *,
        left_name: str = "",
        right_name: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            if parcel_id not in self._fabric:
                raise KeyError(parcel_id)
            meta = self._meta.get(parcel_id, ParcelMetadata())
            left_id = self._next_id()
            right_id = self._next_id()
            cut_a = Point2D(x=float(cut[0][0]), y=float(cut[0][1]), crs=_VIEWER_CRS)
            cut_b = Point2D(x=float(cut[1][0]), y=float(cut[1][1]), crs=_VIEWER_CRS)
            left, right = self._fabric.split_parcel(
                parcel_id, (cut_a, cut_b),
                left_id=left_id, right_id=right_id,
                left_name=left_name or f"{meta.name} (L)",
                right_name=right_name or f"{meta.name} (R)",
            )
            self._meta[left.id] = ParcelMetadata(name=left.name, color=meta.color)
            self._meta[right.id] = ParcelMetadata(name=right.name, color=meta.color)
            self._meta.pop(parcel_id, None)
            return self._dump_parcel(left.id), self._dump_parcel(right.id)

    def merge_parcels(
        self, parcel_ids: list[str], *, name: str = ""
    ) -> dict[str, Any]:
        with self._lock:
            new_id = self._next_id()
            colors = [self._meta.get(pid, ParcelMetadata()).color for pid in parcel_ids]
            self._fabric.merge_parcels(parcel_ids, new_id=new_id, new_name=name or "Merged")
            self._meta[new_id] = ParcelMetadata(name=name or "Merged", color=colors[0] if colors else "#ffd76e")
            for pid in parcel_ids:
                self._meta.pop(pid, None)
            return self._dump_parcel(new_id)

    def clear(self) -> None:
        with self._lock:
            self._fabric = ParcelFabric(snap_tolerance=self._meters_to_degrees(self._tol_m))
            self._meta.clear()

    # ── Snap query ─────────────────────────────────────────────────────────

    def snap_lonlat(self, lon: float, lat: float, tolerance_m: float | None = None) -> dict[str, Any] | None:
        """Return the nearest existing fabric corner within tolerance, else None."""
        tol_m = tolerance_m if tolerance_m is not None else self._tol_m
        tol_deg = self._meters_to_degrees(tol_m)
        with self._lock:
            best: tuple[float, str] | None = None
            for n in self._fabric.nodes():
                d = math.hypot(n.point.x - lon, n.point.y - lat)
                if d <= tol_deg and (best is None or d < best[0]):
                    best = (d, n.id)
            if best is None:
                return None
            node = self._fabric.node(best[1])
            return {
                "node_id": node.id,
                "lon": node.point.x,
                "lat": node.point.y,
                "distance_m": best[0] * 111_000.0,
            }

    # ── Serialisation ──────────────────────────────────────────────────────

    def to_geojson(self) -> dict[str, Any]:
        with self._lock:
            features = [self._dump_parcel(p.id) for p in self._fabric.parcels()]
        return {"type": "FeatureCollection", "features": features}

    def _dump_parcel(self, parcel_id: str) -> dict[str, Any]:
        polygon = self._fabric.get_parcel_polygon(parcel_id)
        ring = self._polygon_to_ring(polygon)
        meta = self._meta.get(parcel_id, ParcelMetadata())
        # Geodesic metrics for the lon/lat ring.
        area_m2 = _geodesic_area_m2(ring)
        perim_m = _geodesic_perimeter_m(ring)
        return {
            "type": "Feature",
            "id": parcel_id,
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                **meta.to_json(),
                "id": parcel_id,
                "vertex_count": len(ring) - 1,
                "area_m2": area_m2,
                "perimeter_m": perim_m,
            },
        }

    @staticmethod
    def _next_id() -> str:
        return f"p_{uuid.uuid4().hex[:10]}"


# ── Geodesic helpers (no external deps) ─────────────────────────────────────


_EARTH_R = 6_378_137.0  # WGS84 equatorial radius, metres.


def _geodesic_area_m2(ring: list[list[float]]) -> float:
    """Spherical-excess area of a closed lon/lat ring on the WGS84 sphere.

    Accurate to ~0.5 % for parcel-sized polygons; replace with pyproj.Geod
    for production-grade ALTA reporting. Sign is positive for any input.
    """
    if len(ring) < 4:
        return 0.0
    total = 0.0
    n = len(ring) - 1
    for i in range(n):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * _EARTH_R * _EARTH_R / 2.0)


def _geodesic_perimeter_m(ring: list[list[float]]) -> float:
    if len(ring) < 2:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        total += haversine_m(ring[i][1], ring[i][0], ring[i + 1][1], ring[i + 1][0])
    return total


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lon/lat points in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in compass degrees (0..360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    brg = math.degrees(math.atan2(y, x))
    return (brg + 360.0) % 360.0


def measure_segments(positions: list[list[float]]) -> dict[str, Any]:
    """Compute per-segment + cumulative measurements for a list of lon/lat points."""
    segments: list[dict[str, float]] = []
    cumulative = 0.0
    for i in range(len(positions) - 1):
        lon1, lat1 = positions[i][0], positions[i][1]
        lon2, lat2 = positions[i + 1][0], positions[i + 1][1]
        d = haversine_m(lat1, lon1, lat2, lon2)
        b = initial_bearing_deg(lat1, lon1, lat2, lon2)
        cumulative += d
        segments.append({"distance_m": d, "bearing_deg": b, "cumulative_m": cumulative})
    closure_distance: float | None = None
    closure_bearing: float | None = None
    if len(positions) >= 3:
        first = positions[0]
        last = positions[-1]
        closure_distance = haversine_m(last[1], last[0], first[1], first[0])
        if closure_distance > 1e-6:
            closure_bearing = initial_bearing_deg(last[1], last[0], first[1], first[0])
    area = _geodesic_area_m2([*positions, positions[0]]) if len(positions) >= 3 else 0.0
    return {
        "segments": segments,
        "total_m": cumulative,
        "area_m2": area,
        "closure_distance_m": closure_distance,
        "closure_bearing_deg": closure_bearing,
    }


__all__ = [
    "EditSession",
    "ParcelMetadata",
    "haversine_m",
    "initial_bearing_deg",
    "measure_segments",
]
