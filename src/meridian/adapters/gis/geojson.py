"""GeoJSON exporter / importer.

Conforms to RFC 7946. Outputs a ``FeatureCollection`` with one Feature
per :class:`Parcel`. The geometry is the boundary polygon converted to
WGS84 (EPSG:4326) per RFC 7946 §4 — we transform on the way out using
:mod:`meridian.math.transforms`. Each feature's ``properties`` carries
the parcel name + metadata + closure stats.

For *projected* deliverables (e.g. State Plane), use the
non-conformant ``allow_other_crs=True`` option which writes the
coordinates in the survey's CRS and adds a ``crs`` member matching
draft-Butler-geojson-crs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget
from meridian.ports.importer import Importer, ImportResult

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.parcel import Parcel
    from meridian.domain.survey import Survey


class GeoJSONExporter(Exporter):
    name = "GeoJSON"
    short_id = "geojson"
    extensions = ("geojson", "json")
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        allow_other_crs = bool(options.get("allow_other_crs", False))
        features: list[dict[str, Any]] = []
        for parcel in survey.parcels:
            if parcel.boundary is None:
                continue
            poly = parcel.boundary.polygon
            if allow_other_crs:
                ring = [[p.x, p.y] for p in poly.exterior]
                holes = [[[p.x, p.y] for p in h] for h in poly.holes]
            else:
                ring = _ring_to_wgs84(poly.exterior, parcel.crs)
                holes = [_ring_to_wgs84(h, parcel.crs) for h in poly.holes]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring, *holes]},
                    "properties": _parcel_props(parcel),
                }
            )
        fc: dict[str, Any] = {"type": "FeatureCollection", "features": features}
        if allow_other_crs:
            fc["crs"] = {"type": "name", "properties": {"name": survey.crs.label()}}
        output_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size,
            metadata={"feature_count": len(features), "rfc7946": not allow_other_crs},
        )


class GeoJSONImporter(Importer):
    name = "GeoJSON"
    short_id = "geojson"
    extensions = ("geojson", "json")

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in {"geojson", "json"}:
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:512]
        except OSError:
            return False
        return '"type"' in head and ("Feature" in head or "FeatureCollection" in head)

    def read(self, path: Path, **options: object) -> ImportResult:
        from meridian.domain.geometry import Point2D, Polygon
        from meridian.domain.parcel import Boundary, Parcel, ParcelMetadata

        data = json.loads(path.read_text(encoding="utf-8"))
        crs = _infer_crs(data, options.get("crs"))
        features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
        parcels: list[Parcel] = []
        for i, feat in enumerate(features):
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Polygon":
                continue
            rings = geom.get("coordinates") or []
            if not rings:
                continue
            ext = tuple(Point2D(x=float(c[0]), y=float(c[1]), crs=crs) for c in rings[0])
            if (ext[0].x, ext[0].y) != (ext[-1].x, ext[-1].y):
                ext = (*ext, ext[0])
            holes = tuple(
                tuple(Point2D(x=float(c[0]), y=float(c[1]), crs=crs) for c in r)
                for r in rings[1:]
            )
            polygon = Polygon(exterior=ext, holes=holes).oriented()
            props = feat.get("properties") or {}
            name = str(props.get("name") or f"Parcel {i+1}")
            boundary = Boundary(
                polygon=polygon,
                misclosure_distance=float(props.get("misclosure_m", 0.0)),
                misclosure_bearing=0.0,
                perimeter=polygon.perimeter(),
                closure_ratio=float(props.get("closure_ratio", float("inf")) or float("inf")),
                point_of_beginning=ext[0],
            )
            parcels.append(
                Parcel(
                    name=name,
                    crs=crs,
                    calls=(),
                    boundary=boundary,
                    metadata=ParcelMetadata(extra=props),
                )
            )
        return ImportResult(parcels=tuple(parcels))


# ── helpers ─────────────────────────────────────────────────────────────────


def _wgs84():
    from meridian.domain.crs import WGS84
    return WGS84


def _ring_to_wgs84(ring: tuple, src_crs) -> list[list[float]]:
    import numpy as np

    from meridian.math.transforms import transform_xy

    xs = np.asarray([p.x for p in ring], dtype=np.float64)
    ys = np.asarray([p.y for p in ring], dtype=np.float64)
    out_x, out_y = transform_xy(xs, ys, src_crs, _wgs84())
    return [[float(x), float(y)] for x, y in zip(out_x, out_y)]


def _parcel_props(parcel) -> dict[str, Any]:
    md = parcel.metadata
    boundary = parcel.boundary
    props: dict[str, Any] = {
        "name": parcel.name,
        "apn": md.apn,
        "address": md.address,
        "grantor": md.grantor,
        "grantee": md.grantee,
        "recording": md.recording,
    }
    if boundary is not None:
        ratio = boundary.closure_ratio
        props.update(
            {
                "perimeter_m": boundary.perimeter,
                "misclosure_m": boundary.misclosure_distance,
                "closure_ratio": None if ratio == float("inf") else ratio,
                "area_m2": boundary.polygon.area(),
            }
        )
    return {k: v for k, v in props.items() if v is not None}


def _infer_crs(data: dict[str, Any], override) -> CRS:
    if override is not None:
        return override  # type: ignore[return-value]
    crs_member = data.get("crs", {}).get("properties", {}).get("name", "") if isinstance(data.get("crs"), dict) else ""
    if "EPSG" in crs_member.upper():
        from meridian.domain.crs import CRS
        try:
            epsg = int(crs_member.upper().split("EPSG:")[-1].split(":")[-1])
            return CRS(epsg=epsg)
        except (ValueError, IndexError):
            pass
    return _wgs84()
