"""Shapefile exporter / importer — built on :mod:`fiona`.

Replaces the prototype's pure-Python Shapefile binary writer with the
GDAL-backed `fiona`. Outputs polygons with a stable property schema:
``name`` (string, 80), ``perimeter`` (float), ``area`` (float),
``misclos`` (float), ``ratio`` (float), ``apn`` (string, 64).

The CRS is written to the ``.prj`` sidecar from the survey's CRS.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget
from meridian.ports.importer import Importer, ImportResult

if TYPE_CHECKING:
    from meridian.domain.parcel import Parcel
    from meridian.domain.survey import Survey


_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "name": "str:80",
        "apn": "str:64",
        "perimeter": "float",
        "area": "float",
        "misclos": "float",
        "ratio": "float",
    },
}


class ShapefileExporter(Exporter):
    name = "Shapefile"
    short_id = "shapefile"
    extensions = ("shp",)
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        try:
            import fiona
            from fiona.crs import from_epsg
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "ShapefileExporter requires fiona. Install with: pip install fiona"
            ) from e

        crs_arg = (
            from_epsg(survey.crs.epsg)
            if survey.crs.epsg is not None
            else (survey.crs.wkt or {})
        )
        with fiona.open(
            str(output_path),
            "w",
            driver="ESRI Shapefile",
            schema=_SCHEMA,
            crs=crs_arg,
        ) as sink:
            for parcel in survey.parcels:
                if parcel.boundary is None:
                    continue
                poly = parcel.boundary.polygon
                ring = [(p.x, p.y) for p in poly.exterior]
                holes = [[(p.x, p.y) for p in h] for h in poly.holes]
                sink.write(
                    {
                        "geometry": {"type": "Polygon", "coordinates": [ring, *holes]},
                        "properties": {
                            "name": parcel.name[:80],
                            "apn": (parcel.metadata.apn or "")[:64],
                            "perimeter": float(parcel.boundary.perimeter),
                            "area": float(poly.area()),
                            "misclos": float(parcel.boundary.misclosure_distance),
                            "ratio": (
                                None
                                if parcel.boundary.closure_ratio == float("inf")
                                else float(parcel.boundary.closure_ratio)
                            ),
                        },
                    }
                )
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            metadata={"feature_count": len(survey.parcels)},
        )


class ShapefileImporter(Importer):
    name = "Shapefile"
    short_id = "shapefile"
    extensions = ("shp",)

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") == "shp" and path.exists()

    def read(self, path: Path, **options: object) -> ImportResult:
        try:
            import fiona
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("fiona required") from e
        from meridian.domain.crs import CRS
        from meridian.domain.geometry import Point2D, Polygon
        from meridian.domain.parcel import Boundary, Parcel, ParcelMetadata

        parcels: list[Parcel] = []
        with fiona.open(str(path)) as src:
            crs_dict = dict(src.crs or {})
            epsg = crs_dict.get("init", "").upper().replace("EPSG:", "") if crs_dict else None
            crs = (
                CRS(epsg=int(epsg)) if epsg and epsg.isdigit()
                else CRS(wkt=src.crs_wkt) if src.crs_wkt
                else None
            )
            if crs is None:
                raise ValueError(f"Shapefile {path} has no usable CRS metadata.")
            for i, feat in enumerate(src):
                geom = feat["geometry"]
                if geom["type"] != "Polygon":
                    continue
                rings = geom["coordinates"]
                ext = tuple(Point2D(x=float(c[0]), y=float(c[1]), crs=crs) for c in rings[0])
                if (ext[0].x, ext[0].y) != (ext[-1].x, ext[-1].y):
                    ext = (*ext, ext[0])
                holes = tuple(
                    tuple(Point2D(x=float(c[0]), y=float(c[1]), crs=crs) for c in r)
                    for r in rings[1:]
                )
                polygon = Polygon(exterior=ext, holes=holes).oriented()
                props = dict(feat["properties"])
                name = str(props.get("name") or f"Parcel {i+1}")
                boundary = Boundary(
                    polygon=polygon,
                    misclosure_distance=float(props.get("misclos") or 0.0),
                    misclosure_bearing=0.0,
                    perimeter=float(props.get("perimeter") or polygon.perimeter()),
                    closure_ratio=float(props.get("ratio") or float("inf")),
                    point_of_beginning=ext[0],
                )
                parcels.append(
                    Parcel(
                        name=name,
                        crs=crs,
                        calls=(),
                        boundary=boundary,
                        metadata=ParcelMetadata(apn=props.get("apn"), extra=props),
                    )
                )
        return ImportResult(parcels=tuple(parcels))
