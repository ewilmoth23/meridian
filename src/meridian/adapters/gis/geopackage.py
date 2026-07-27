"""GeoPackage exporter / importer — built on :mod:`fiona`.

GeoPackage is the OGC standard alternative to Shapefile. One file, no
sidecars, supports multiple layers, full Unicode column names, no 254-
character limit. We default exports to GeoPackage when the user doesn't
care about the legacy ESRI ecosystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget

if TYPE_CHECKING:
    from meridian.domain.survey import Survey


_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "name": "str",
        "apn": "str",
        "perimeter_m": "float",
        "area_m2": "float",
        "misclosure_m": "float",
        "closure_ratio": "float",
        "grantor": "str",
        "grantee": "str",
        "recording": "str",
    },
}


class GeoPackageExporter(Exporter):
    name = "GeoPackage"
    short_id = "geopackage"
    extensions = ("gpkg",)
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        try:
            import fiona
            from fiona.crs import from_epsg
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("GeoPackageExporter requires fiona") from e

        layer = str(options.get("layer", "parcels"))
        crs_arg = (
            from_epsg(survey.crs.epsg)
            if survey.crs.epsg is not None
            else (survey.crs.wkt or {})
        )
        # GeoPackage supports overwrite of an existing file via 'w' mode,
        # but multi-layer use should append; we keep the v1 simple.
        with fiona.open(
            str(output_path),
            "w",
            driver="GPKG",
            layer=layer,
            schema=_SCHEMA,
            crs=crs_arg,
        ) as sink:
            for parcel in survey.parcels:
                if parcel.boundary is None:
                    continue
                poly = parcel.boundary.polygon
                ring = [(p.x, p.y) for p in poly.exterior]
                holes = [[(p.x, p.y) for p in h] for h in poly.holes]
                ratio = parcel.boundary.closure_ratio
                sink.write(
                    {
                        "geometry": {"type": "Polygon", "coordinates": [ring, *holes]},
                        "properties": {
                            "name": parcel.name,
                            "apn": parcel.metadata.apn,
                            "perimeter_m": float(parcel.boundary.perimeter),
                            "area_m2": float(poly.area()),
                            "misclosure_m": float(parcel.boundary.misclosure_distance),
                            "closure_ratio": None if ratio == float("inf") else float(ratio),
                            "grantor": parcel.metadata.grantor,
                            "grantee": parcel.metadata.grantee,
                            "recording": parcel.metadata.recording,
                        },
                    }
                )
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            metadata={"feature_count": len(survey.parcels), "layer": layer},
        )
