"""Write a :class:`~meridian.domain.pointcloud.Surface` (TIN + contours)
to DXF.

Layers used:

* ``CONTOURS`` — every contour line.
* ``CONTOURS-INDEX`` — every Nth contour, drawn heavier for plat clarity.
* ``TIN-EDGES`` — optionally, the triangle edges (off by default; on for
  QA).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.pointcloud import Surface


def write_surface_dxf(
    surface: Surface,
    output_path: Path,
    *,
    index_every: int = 5,
    interval_m: float = 1.0,
    include_tin: bool = False,
    dxf_version: str = "R2018",
) -> int:
    """Write contours (and optionally the TIN) to a DXF file.

    Returns the number of bytes written.
    """
    try:
        import ezdxf
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("ezdxf is required") from e

    doc = ezdxf.new(dxf_version, setup=True)
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add(name="DASHED", pattern="A,1,-0.5", description="dashed")

    contours_layer = doc.layers.add("CONTOURS") if "CONTOURS" not in doc.layers else doc.layers.get("CONTOURS")
    contours_layer.color = 8
    index_layer = (
        doc.layers.add("CONTOURS-INDEX")
        if "CONTOURS-INDEX" not in doc.layers
        else doc.layers.get("CONTOURS-INDEX")
    )
    index_layer.color = 3
    index_layer.dxf.lineweight = 35

    msp = doc.modelspace()
    for contour in surface.contours:
        idx_int = round(contour.elevation / interval_m)
        is_index = abs((contour.elevation / interval_m) - idx_int) < 1e-6 and (idx_int % index_every == 0)
        layer = "CONTOURS-INDEX" if is_index else "CONTOURS"
        for poly in contour.polylines:
            if poly.shape[0] < 2:
                continue
            msp.add_lwpolyline(
                [(float(p[0]), float(p[1])) for p in poly],
                dxfattribs={"layer": layer, "elevation": contour.elevation},
            )
        if is_index and contour.polylines:
            label_pt = contour.polylines[0][len(contour.polylines[0]) // 2]
            msp.add_text(
                f"{contour.elevation:,.2f}",
                dxfattribs={"layer": "CONTOURS-INDEX", "height": interval_m * 0.6},
            ).set_placement((float(label_pt[0]), float(label_pt[1])))

    if include_tin:
        tin_layer = (
            doc.layers.add("TIN-EDGES")
            if "TIN-EDGES" not in doc.layers
            else doc.layers.get("TIN-EDGES")
        )
        tin_layer.color = 250
        v = surface.tin.vertices
        for tri in surface.tin.triangles:
            a, b, c = v[tri[0]], v[tri[1]], v[tri[2]]
            msp.add_3dface(
                [
                    (float(a[0]), float(a[1]), float(a[2])),
                    (float(b[0]), float(b[1]), float(b[2])),
                    (float(c[0]), float(c[1]), float(c[2])),
                    (float(a[0]), float(a[1]), float(a[2])),
                ],
                dxfattribs={"layer": "TIN-EDGES"},
            )

    doc.saveas(str(output_path))
    return output_path.stat().st_size if output_path.exists() else 0
