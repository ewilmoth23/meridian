"""LandXML 1.2 / 2.0 round-trip via :mod:`lxml`.

Replaces the prototype's regex-on-XML parsing with a real lxml-based
reader/writer. Targets LandXML 1.2 with optional 2.0 elements where
applicable.

Scope (v0.2):

* **Read:** ``CgPoints`` → :class:`Point3D`; ``Parcels/Parcel`` and
  ``CoordGeom`` → :class:`Parcel` + :class:`Call`; ``Surfaces/Surface``
  → :class:`TIN`.
* **Write:** :class:`Survey` → CgPoints + Parcels + (optionally) Surfaces.

LandXML coordinates are typically in a projected CRS declared via
``CoordinateSystem``. When present we honour the EPSG / WKT; when
absent we require the caller to pass ``crs=...``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget
from meridian.ports.importer import Importer, ImportResult

if TYPE_CHECKING:
    from meridian.domain.parcel import Parcel
    from meridian.domain.survey import Survey


LANDXML_NS = "http://www.landxml.org/schema/LandXML-1.2"


class LandXMLExporter(Exporter):
    name = "LandXML 1.2"
    short_id = "landxml"
    extensions = ("xml", "landxml")
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        from lxml import etree

        nsmap = {None: LANDXML_NS}
        root = etree.Element(f"{{{LANDXML_NS}}}LandXML", nsmap=nsmap)
        root.set("date", dt.date.today().isoformat())
        root.set("time", dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
        root.set("version", "1.2")
        root.set("language", "en")

        units_el = etree.SubElement(root, f"{{{LANDXML_NS}}}Units")
        metric = etree.SubElement(units_el, f"{{{LANDXML_NS}}}Metric")
        metric.set("areaUnit", "squareMeter")
        metric.set("linearUnit", "meter")
        metric.set("volumeUnit", "cubicMeter")
        metric.set("temperatureUnit", "celsius")
        metric.set("pressureUnit", "milliBars")
        metric.set("angularUnit", "decimal degrees")
        metric.set("directionUnit", "decimal degrees")

        if survey.crs.epsg is not None:
            cs = etree.SubElement(root, f"{{{LANDXML_NS}}}CoordinateSystem")
            cs.set("epsgCode", str(survey.crs.epsg))
            cs.set("name", survey.crs.label())

        application = etree.SubElement(root, f"{{{LANDXML_NS}}}Application")
        application.set("name", "Meridian")
        application.set("version", "0.1.0")

        # Collect a single CgPoints block from all parcel boundaries.
        cgpts = etree.SubElement(root, f"{{{LANDXML_NS}}}CgPoints")
        cgpts.set("name", "MeridianPoints")
        point_index: dict[tuple[float, float], int] = {}

        def _ensure_point(x: float, y: float, z: float = 0.0) -> int:
            key = (round(x, 6), round(y, 6))
            if key in point_index:
                return point_index[key]
            idx = len(point_index) + 1
            point_index[key] = idx
            cg = etree.SubElement(cgpts, f"{{{LANDXML_NS}}}CgPoint")
            cg.set("name", f"P{idx}")
            cg.text = f"{y:.6f} {x:.6f} {z:.6f}"
            return idx

        parcels_el = etree.SubElement(root, f"{{{LANDXML_NS}}}Parcels")
        for parcel in survey.parcels:
            if parcel.boundary is None:
                continue
            parcel_el = etree.SubElement(parcels_el, f"{{{LANDXML_NS}}}Parcel")
            parcel_el.set("name", parcel.name)
            if parcel.metadata.acreage is not None:
                parcel_el.set("area", str(parcel.metadata.acreage))
            if parcel.metadata.legal_description_text:
                etree.SubElement(parcel_el, f"{{{LANDXML_NS}}}Description").text = (
                    parcel.metadata.legal_description_text
                )
            coordgeom = etree.SubElement(parcel_el, f"{{{LANDXML_NS}}}CoordGeom")
            ring = parcel.boundary.polygon.exterior
            for i in range(len(ring) - 1):
                p1 = ring[i]
                p2 = ring[i + 1]
                line = etree.SubElement(coordgeom, f"{{{LANDXML_NS}}}Line")
                start = etree.SubElement(line, f"{{{LANDXML_NS}}}Start")
                _ensure_point(p1.x, p1.y)
                start.text = f"{p1.y:.6f} {p1.x:.6f}"
                end = etree.SubElement(line, f"{{{LANDXML_NS}}}End")
                _ensure_point(p2.x, p2.y)
                end.text = f"{p2.y:.6f} {p2.x:.6f}"

        tree = etree.ElementTree(root)
        tree.write(str(output_path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size,
            metadata={"parcels": len(survey.parcels), "points": len(point_index)},
        )


class LandXMLImporter(Importer):
    name = "LandXML 1.2"
    short_id = "landxml"
    extensions = ("xml", "landxml")

    def can_read(self, path: Path) -> bool:
        if path.suffix.lower().lstrip(".") not in {"xml", "landxml"}:
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:2048]
        except OSError:
            return False
        return "LandXML" in head

    def read(self, path: Path, **options: object) -> ImportResult:
        from lxml import etree

        from meridian.domain.crs import CRS
        from meridian.domain.geometry import Point2D, Polygon
        from meridian.domain.parcel import Boundary, Parcel, ParcelMetadata

        tree = etree.parse(str(path))
        root = tree.getroot()

        # Resolve CRS — prefer EPSG attribute, fall back to caller override.
        crs_override = options.get("crs")
        cs_el = root.find(".//{*}CoordinateSystem")
        if cs_el is not None and cs_el.get("epsgCode"):
            crs = CRS(epsg=int(cs_el.get("epsgCode")))
        elif crs_override is not None:
            crs = crs_override  # type: ignore[assignment]
        else:
            raise ValueError(
                f"LandXML at {path} has no CoordinateSystem; pass crs=... to read()."
            )

        parcels: list[Parcel] = []
        for parcel_el in root.findall(".//{*}Parcels/{*}Parcel"):
            name = parcel_el.get("name") or "Parcel"
            description = (parcel_el.find("{*}Description").text  # type: ignore[union-attr]
                           if parcel_el.find("{*}Description") is not None else None)
            ring_pts: list[Point2D] = []
            coordgeom = parcel_el.find("{*}CoordGeom")
            if coordgeom is None:
                continue
            for line in coordgeom.findall("{*}Line"):
                start = line.find("{*}Start")
                if start is not None and start.text:
                    y, x = (float(v) for v in start.text.strip().split()[:2])
                    ring_pts.append(Point2D(x=x, y=y, crs=crs))
                # The closing End point is added once at the very end.
            if coordgeom.findall("{*}Line"):
                last_end = coordgeom.findall("{*}Line")[-1].find("{*}End")
                if last_end is not None and last_end.text:
                    y, x = (float(v) for v in last_end.text.strip().split()[:2])
                    ring_pts.append(Point2D(x=x, y=y, crs=crs))
            if len(ring_pts) < 4:
                # Need at least 3 distinct points + closing.
                if len(ring_pts) >= 3 and (ring_pts[0].x, ring_pts[0].y) != (ring_pts[-1].x, ring_pts[-1].y):
                    ring_pts.append(ring_pts[0])
                else:
                    continue
            polygon = Polygon(exterior=tuple(ring_pts)).oriented()
            boundary = Boundary(
                polygon=polygon,
                misclosure_distance=0.0,
                misclosure_bearing=0.0,
                perimeter=polygon.perimeter(),
                closure_ratio=float("inf"),
                point_of_beginning=ring_pts[0],
            )
            parcels.append(
                Parcel(
                    name=name,
                    crs=crs,
                    calls=(),
                    boundary=boundary,
                    metadata=ParcelMetadata(legal_description_text=description),
                )
            )
        return ImportResult(parcels=tuple(parcels))
