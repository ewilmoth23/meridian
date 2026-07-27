"""KML / KMZ exporter (and KML importer).

We *do not* recommend KML as a deliverable — it loses CAD layer
fidelity. We ship it for two reasons:

* Backwards compatibility with Google Earth / clients on consumer
  devices.
* It's a fallback when the user hasn't installed the Atlas-required
  optional deps.

KML coordinates are always WGS84 lon/lat/alt per the OGC KML 2.3 spec.
We transform on the way out using :mod:`meridian.math.transforms`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.ports.exporter import Exporter, ExportResult, ExportTarget

if TYPE_CHECKING:
    from meridian.domain.survey import Survey


KML_NS = "http://www.opengis.net/kml/2.2"


class KMLExporter(Exporter):
    name = "KML"
    short_id = "kml"
    extensions = ("kml", "kmz")
    target = ExportTarget.SURVEY

    def export_survey(self, survey: Survey, output_path: Path, **options: object) -> ExportResult:
        from lxml import etree

        kml = etree.Element(f"{{{KML_NS}}}kml", nsmap={None: KML_NS})
        doc = etree.SubElement(kml, f"{{{KML_NS}}}Document")
        etree.SubElement(doc, f"{{{KML_NS}}}name").text = survey.name
        for parcel in survey.parcels:
            if parcel.boundary is None:
                continue
            placemark = etree.SubElement(doc, f"{{{KML_NS}}}Placemark")
            etree.SubElement(placemark, f"{{{KML_NS}}}name").text = parcel.name
            if parcel.metadata.legal_description_text:
                etree.SubElement(placemark, f"{{{KML_NS}}}description").text = parcel.metadata.legal_description_text
            polygon_el = etree.SubElement(placemark, f"{{{KML_NS}}}Polygon")
            outer = etree.SubElement(polygon_el, f"{{{KML_NS}}}outerBoundaryIs")
            ring = etree.SubElement(outer, f"{{{KML_NS}}}LinearRing")
            etree.SubElement(ring, f"{{{KML_NS}}}coordinates").text = _ring_to_kml(parcel.boundary.polygon.exterior, parcel.crs)
            for hole in parcel.boundary.polygon.holes:
                inner = etree.SubElement(polygon_el, f"{{{KML_NS}}}innerBoundaryIs")
                hring = etree.SubElement(inner, f"{{{KML_NS}}}LinearRing")
                etree.SubElement(hring, f"{{{KML_NS}}}coordinates").text = _ring_to_kml(hole, parcel.crs)

        tree = etree.ElementTree(kml)
        if str(output_path).lower().endswith(".kmz"):
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("doc.kml", etree.tostring(tree, xml_declaration=True, encoding="UTF-8", pretty_print=True))
        else:
            tree.write(str(output_path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
        return ExportResult(
            output_path=output_path,
            bytes_written=output_path.stat().st_size,
            metadata={"feature_count": len(survey.parcels)},
        )


def _ring_to_kml(ring: tuple, src_crs) -> str:
    import numpy as np

    from meridian.domain.crs import WGS84
    from meridian.math.transforms import transform_xy

    xs = np.asarray([p.x for p in ring], dtype=np.float64)
    ys = np.asarray([p.y for p in ring], dtype=np.float64)
    if src_crs == WGS84:
        out_x, out_y = xs, ys
    else:
        out_x, out_y = transform_xy(xs, ys, src_crs, WGS84)
    return " ".join(f"{x:.10f},{y:.10f},0" for x, y in zip(out_x, out_y))
