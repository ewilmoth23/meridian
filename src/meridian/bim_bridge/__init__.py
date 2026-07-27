"""Survey ↔ BIM round-trip via IFC 4.3 (v0.7).

IFC 4.3 (2024) added alignment / infrastructure entities. Existing tools
(Autodesk Tandem, Bentley iTwin, Trimble Connect) push BIM → DT one way;
none write surveyor-authoritative changes back.

Meridian becomes the survey-of-record source and writes back into the
IFC alignment; in the other direction, design-intent footprints from the
architect overlay the parcel as an "intent" layer for as-built
reconciliation.

Status: planning stub for v0.7.

Components (to be implemented):

* ``ifc_reader.py`` — read IFC 4.3 alignment / monument / parcel entities
  via :mod:`ifcopenshell`.
* ``ifc_writer.py`` — write Meridian's adjusted boundary back as
  ``IfcAlignment`` plus ``IfcGeographicCRS`` linkage.
* ``intent_overlay.py`` — render design-intent geometry as a non-
  authoritative layer in the CAD view and in Atlas.
* ``conflict_report.py`` — produce an as-built-vs-intent conflict report
  for the architect's QA workflow.
"""

from __future__ import annotations

from meridian.bim_bridge.ifc_io import (
    BIMConflict,
    BIMConflictReport,
    export_survey_to_ifc,
    import_ifc_alignments,
    reconcile_intent_vs_asbuilt,
)

__all__ = [
    "BIMConflict",
    "BIMConflictReport",
    "export_survey_to_ifc",
    "import_ifc_alignments",
    "reconcile_intent_vs_asbuilt",
]
