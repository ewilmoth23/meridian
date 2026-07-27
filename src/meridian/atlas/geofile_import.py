"""Importers that turn surveyor file formats into Cesium-friendly JSON.

Every importer accepts raw bytes (so the viewer can drag-drop a file and POST
it directly), parses with the relevant Python adapter, and returns a single
GeoJSON ``FeatureCollection`` with 3D coordinates the Atlas viewer can render
without further processing.

Supported formats (v0):

* **DXF / DWG-as-DXF** — via :mod:`ezdxf`. Lines, polylines, circles, arcs,
  3D polygon meshes, points, text. Layer names are preserved as
  ``properties.layer`` so the viewer can colour by layer and drape on terrain.
* **LAS / LAZ** — via :mod:`laspy`. Returns a sub-sampled point cloud as a
  ``MultiPoint`` feature with classification + intensity attributes; the
  viewer renders it via Cesium ``PointPrimitive``.
* **LandXML** — pure XML parsing; pulls surfaces (TIN), parcels, and
  alignments. Surfaces become ``Polygon`` features (one per face), parcels
  become ``Polygon`` features.

For all three formats: if the file contains a CRS hint we honour it; otherwise
we accept caller-supplied ``source_crs`` (an EPSG code) and project to WGS84
lon/lat for the viewer. Without a CRS hint, coordinates are passed through
as-is and assumed already to be lon/lat — a sensible default for the
"drag-drop a sample file" use case.
"""

from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

# ── Common dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ImportResult:
    """A normalised result that maps cleanly to JSON over HTTP."""

    feature_collection: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "ImportResult",
            "feature_collection": self.feature_collection,
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


# ── DXF ─────────────────────────────────────────────────────────────────────


# Minimal AC1009 (R12) preamble for "fragment" DXFs that contain only an
# ENTITIES section. Some mechanical-CAD / laser-cutter tools emit DXFs in
# this reduced form. ezdxf's strict parser refuses them; wrapping with this
# header lets recover.read() pick them up.
_DXF_FRAGMENT_PREAMBLE = (
    "0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n"
    "0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n1\n"
    "0\nLAYER\n2\n0\n70\n0\n62\n7\n6\nCONTINUOUS\n0\nENDTAB\n0\nENDSEC\n"
).encode("ascii")
_DXF_FRAGMENT_TRAILER = b"0\nENDSEC\n0\nEOF\n"


def _manual_parse_dxf_entities(
    data: bytes, transform: Callable[[float, float], tuple[float, float]]
) -> dict[str, Any] | None:
    """Tier-3 fallback: a minimal DXF entity parser implemented here, no
    ezdxf round-trip. Walks the group-code / value pairs and extracts the
    common surveying + CAD primitives.

    Handles LINE, LWPOLYLINE, POLYLINE (with VERTEX records), CIRCLE, ARC,
    POINT, TEXT, MTEXT. Skips anything else. Returns ``None`` if no entities
    found or the input doesn't look like DXF.

    Used when ezdxf refuses the file outright (e.g. mechanical-CAD fragment
    DXFs missing the HEADER / TABLES sections that ezdxf requires).
    """
    text = data.decode("ascii", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        return None
    # Pair lines into (code, value). Skip records where the code line isn't
    # numeric — defensive against junk content.
    pairs: list[tuple[int, str]] = []
    i = 0
    while i + 1 < len(lines):
        try:
            code = int(lines[i])
        except ValueError:
            i += 1
            continue
        pairs.append((code, lines[i + 1]))
        i += 2

    # Walk pairs, splitting at every code-0 to delimit entities.
    entities: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for code, value in pairs:
        upper = value.upper()
        if code == 0:
            if cur is not None:
                entities.append(cur)
            if upper in ("SECTION", "ENDSEC", "EOF", "TABLE", "ENDTAB", "BLOCK", "ENDBLK"):
                cur = None
            else:
                cur = {"type": upper, "pairs": []}
        elif cur is not None:
            cur["pairs"].append((code, value))
    if cur is not None:
        entities.append(cur)

    features: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for ent in entities:
        kind = ent["type"]
        counts[kind] = counts.get(kind, 0) + 1
        feat = _manual_entity_to_feature(kind, ent["pairs"], transform)
        if feat is not None:
            features.append(feat)
    return {"features": features, "counts": counts}


def _manual_entity_to_feature(
    kind: str,
    pairs: list[tuple[int, str]],
    transform: Callable[[float, float], tuple[float, float]],
) -> dict[str, Any] | None:
    """Map a flat list of (group_code, value) pairs into a GeoJSON feature."""
    layer = "0"
    color = 7
    text_value: str | None = None
    # Single-point / center coordinates (common: code 10/20/30, 11/21/31).
    primary_xs: list[float] = []
    primary_ys: list[float] = []
    primary_zs: list[float] = []
    secondary_x: float | None = None
    secondary_y: float | None = None
    secondary_z: float = 0.0
    radius: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    closed = False

    def _f(s: str) -> float | None:
        try:
            return float(s)
        except ValueError:
            return None

    for code, value in pairs:
        if code == 8:
            layer = value
        elif code == 62:
            ci = _f(value)
            if ci is not None:
                color = int(ci)
        elif code == 1:
            text_value = value
        elif code == 10:
            v = _f(value)
            if v is not None:
                primary_xs.append(v)
        elif code == 20:
            v = _f(value)
            if v is not None:
                primary_ys.append(v)
        elif code == 30:
            v = _f(value)
            if v is not None:
                primary_zs.append(v)
        elif code == 11:
            secondary_x = _f(value)
        elif code == 21:
            secondary_y = _f(value)
        elif code == 31:
            v = _f(value)
            if v is not None:
                secondary_z = v
        elif code == 40:
            radius = _f(value)
        elif code == 50:
            start_angle = _f(value)
        elif code == 51:
            end_angle = _f(value)
        elif code == 70:
            v = _f(value)
            if v is not None and (int(v) & 1):
                closed = True

    # Make sure z lists match length.
    while len(primary_zs) < len(primary_xs):
        primary_zs.append(0.0)

    props = {"layer": layer, "color": color, "dxf_type": kind}
    if text_value is not None:
        props["text"] = text_value

    def _xy(x: float, y: float, z: float = 0.0) -> list[float]:
        tx, ty = transform(x, y)
        return [tx, ty, z]

    if kind == "LINE":
        if not primary_xs or secondary_x is None or not primary_ys or secondary_y is None:
            return None
        z0 = primary_zs[0] if primary_zs else 0.0
        return {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "LineString",
                "coordinates": [_xy(primary_xs[0], primary_ys[0], z0), _xy(secondary_x, secondary_y, secondary_z)],
            },
        }
    if kind in ("LWPOLYLINE", "POLYLINE"):
        n = min(len(primary_xs), len(primary_ys))
        if n < 2:
            return None
        coords = [_xy(primary_xs[i], primary_ys[i], primary_zs[i] if i < len(primary_zs) else 0.0) for i in range(n)]
        if closed and n >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            return {
                "type": "Feature",
                "properties": {**props, "closed": True},
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }
        return {"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": coords}}
    if kind == "CIRCLE":
        if not primary_xs or not primary_ys or radius is None:
            return None
        z0 = primary_zs[0] if primary_zs else 0.0
        coords = _circle_coords(primary_xs[0], primary_ys[0], z0, radius, transform, segments=64)
        return {
            "type": "Feature",
            "properties": {**props, "radius": radius},
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        }
    if kind == "ARC":
        if not primary_xs or not primary_ys or radius is None or start_angle is None or end_angle is None:
            return None
        z0 = primary_zs[0] if primary_zs else 0.0
        a0 = math.radians(start_angle)
        a1 = math.radians(end_angle)
        if a1 < a0:
            a1 += 2 * math.pi
        coords = _arc_coords(primary_xs[0], primary_ys[0], z0, radius, a0, a1, transform, segments=48)
        return {
            "type": "Feature",
            "properties": {**props, "radius": radius},
            "geometry": {"type": "LineString", "coordinates": coords},
        }
    if kind == "POINT":
        if not primary_xs or not primary_ys:
            return None
        z0 = primary_zs[0] if primary_zs else 0.0
        return {
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": _xy(primary_xs[0], primary_ys[0], z0)},
        }
    if kind in ("TEXT", "MTEXT"):
        if not primary_xs or not primary_ys:
            return None
        z0 = primary_zs[0] if primary_zs else 0.0
        return {
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": _xy(primary_xs[0], primary_ys[0], z0)},
        }
    return None


def _try_wrap_dxf_fragment(data: bytes) -> bytes | None:
    """If ``data`` contains an ENTITIES section that ezdxf couldn't parse on
    its own (typical of mechanical-CAD / laser-cutter exports that emit
    "fragment" DXFs with empty or missing HEADER/TABLES), extract just the
    entities and rebuild with a minimal synthetic preamble.

    Also strips blank lines / non-pair whitespace between entity records —
    ezdxf strictly alternates group-code / value lines and rejects any
    blank line in between (a common quirk of hand-rolled DXF exporters).

    Returns None when no ENTITIES section can be located (so the caller
    falls through to the original parse error).
    """
    import re

    text = data.decode("ascii", errors="replace")
    # Locate ENTITIES section. DXF group-code form is "0\nSECTION\n2\nENTITIES".
    sec_pattern = re.compile(
        r"^[ \t]*0[ \t]*$\s*^[ \t]*SECTION[ \t]*$\s*^[ \t]*2[ \t]*$\s*^[ \t]*ENTITIES[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    m = sec_pattern.search(text)
    if not m:
        return None
    entities_start = m.start()
    # Where does the entities body end? Either an explicit ENDSEC or EOF.
    endsec_pattern = re.compile(
        r"^[ \t]*0[ \t]*$\s*^[ \t]*ENDSEC[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    em = endsec_pattern.search(text, m.end())
    raw_block = text[entities_start : (em.end() if em else len(text))]
    # Normalize: drop blank lines and trim each remaining line. ezdxf needs
    # strict code/value pairs on consecutive non-empty lines.
    cleaned_lines = [ln.strip() for ln in raw_block.splitlines() if ln.strip()]
    # Make sure block ends with the ENDSEC pair (insert if missing).
    if not (
        len(cleaned_lines) >= 2
        and cleaned_lines[-2] == "0"
        and cleaned_lines[-1].upper() == "ENDSEC"
    ):
        cleaned_lines.extend(["0", "ENDSEC"])
    cleaned = "\n".join(cleaned_lines) + "\n"
    return _DXF_FRAGMENT_PREAMBLE + cleaned.encode("ascii", errors="ignore") + b"0\nEOF\n"


def import_dxf(
    data: bytes,
    *,
    source_crs_epsg: int | None = None,
) -> ImportResult:
    """Parse DXF bytes into a GeoJSON FeatureCollection.

    Each AutoCAD entity becomes a feature whose ``properties`` carry the
    layer, color (AutoCAD color index), linetype, and original DXF type.
    Coordinates are passed through verbatim; if ``source_crs_epsg`` is given,
    they're transformed to WGS84.

    Uses ``ezdxf.recover.read`` which handles:
      • binary DXF input via BytesIO (no UTF-8 decoding required)
      • automatic encoding detection ($DWGCODEPAGE / 1.18 sentinel)
      • minor structural damage / partial recovery
      • all DXF versions ezdxf supports (R12 → R2018)

    The previous implementation used ``ezdxf.read(StringIO(decoded))`` which
    SILENTLY produced an empty modelspace for many real-world DXFs because
    UTF-8 decoding mangled the file's encoded content. The audit/recovery
    path is the documented way to handle arbitrary user-uploaded files.
    """
    from ezdxf import recover

    transform = _make_transform(source_crs_epsg)
    features: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    warnings: list[str] = []
    auditor = None

    # Tier 1 — try the standard ezdxf recover path. Handles 99 % of
    # well-formed DXFs including R12 → R2018, with auto-encoding detection.
    parsed_via = "ezdxf.recover.read"
    doc: Any = None
    try:
        doc, auditor = recover.read(io.BytesIO(data))
    except Exception as exc1:
        # Tier 2 — try wrapping a fragment / minimal-DXF with synthetic
        # HEADER + TABLES. Some laser-cutter / mechanical-CAD tools emit
        # entities-only DXFs that ezdxf refuses without a HEADER section.
        wrapped = _try_wrap_dxf_fragment(data)
        if wrapped is not None:
            try:
                doc, auditor = recover.read(io.BytesIO(wrapped))
                parsed_via = "ezdxf.recover.read after fragment-wrap"
            except Exception:
                doc = None
        if doc is None:
            # Tier 3 — manual mini-parser for the entities-only case.
            # Bypasses ezdxf entirely. Handles LINE / LWPOLYLINE / POLYLINE /
            # CIRCLE / ARC / POINT / TEXT — the common surveying + CAD
            # primitives. If THIS fails too, the file is genuinely broken.
            try:
                manual = _manual_parse_dxf_entities(data, transform)
            except Exception as exc3:
                raise ValueError(
                    f"DXF parse failed (ezdxf and manual fallback both errored): "
                    f"ezdxf={exc1!s}; manual={exc3!s}"
                ) from exc1
            if manual is None or not manual["features"]:
                raise ValueError(f"DXF parse failed: {exc1}") from exc1
            features = manual["features"]
            counts = manual["counts"]
            warnings.append(
                "Parsed via fallback mini-parser — file lacked a usable DXF "
                "structure for ezdxf. Recovered entity primitives only."
            )
            bbox = _features_bbox(features)
            return ImportResult(
                feature_collection={"type": "FeatureCollection", "features": features},
                summary={
                    "format": "dxf",
                    "entity_counts": counts,
                    "feature_count": len(features),
                    "bbox": bbox,
                    "layers": sorted({f["properties"].get("layer", "") for f in features}),
                    "parser": "manual_fallback",
                },
                warnings=tuple(warnings),
            )

    msp = doc.modelspace()

    for entity in msp:
        kind = entity.dxftype()
        counts[kind] = counts.get(kind, 0) + 1
        try:
            feat = _dxf_entity_to_feature(entity, transform)
        except Exception as exc:  # pragma: no cover — defensive: skip one bad entity, don't fail the whole import
            warnings.append(f"Skipped {kind} entity (parse error): {exc}")
            continue
        if feat is not None:
            features.append(feat)
        else:
            warnings.append(f"Unsupported DXF entity skipped: {kind}")

    if auditor and getattr(auditor, "errors", None):
        warnings.append(f"DXF audit reported {len(auditor.errors)} structural issue(s); recovery succeeded.")

    bbox = _features_bbox(features)
    return ImportResult(
        feature_collection={"type": "FeatureCollection", "features": features},
        summary={
            "format": "dxf",
            "entity_counts": counts,
            "feature_count": len(features),
            "bbox": bbox,
            "layers": sorted({f["properties"].get("layer", "") for f in features}),
            "parser": parsed_via,
        },
        warnings=tuple(dict.fromkeys(warnings)),  # preserve order, de-dup
    )


def _dxf_entity_to_feature(
    entity: Any, transform: Callable[[float, float], tuple[float, float]],
) -> dict[str, Any] | None:
    """Map a single ezdxf entity to a GeoJSON feature, or ``None`` if unsupported."""
    kind = entity.dxftype()
    layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
    color = entity.dxf.color if entity.dxf.hasattr("color") else 7
    props: dict[str, Any] = {"layer": layer, "color": color, "dxf_type": kind}

    def pt(p: Any) -> list[float]:
        x, y = transform(float(p[0]), float(p[1]))
        z = float(p[2]) if len(p) > 2 else 0.0
        return [x, y, z]

    if kind == "POINT":
        return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": pt(entity.dxf.location)}}
    if kind == "LINE":
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "LineString",
                             "coordinates": [pt(entity.dxf.start), pt(entity.dxf.end)]}}
    if kind == "LWPOLYLINE":
        coords = []
        # LWPOLYLINE: stored as (x, y, start_w, end_w, bulge); we want xy + 0 z.
        for x, y, *_ in entity.get_points("xy"):
            tx, ty = transform(float(x), float(y))
            coords.append([tx, ty, 0.0])
        if not coords:
            return None
        is_closed = bool(getattr(entity, "closed", False))
        if is_closed and len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            return {"type": "Feature", "properties": {**props, "closed": True},
                    "geometry": {"type": "Polygon", "coordinates": [coords]}}
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "LineString", "coordinates": coords}}
    if kind == "POLYLINE":
        # mypy: re-bind name; same intent as LWPOLYLINE branch above.
        coords = []
        # POLYLINE has VERTEX sub-entities; ezdxf exposes them as a method or
        # attribute depending on version. Try the modern method first.
        try:
            verts = entity.vertices() if callable(entity.vertices) else entity.vertices
        except Exception:
            verts = []
        for v in verts:
            try:
                loc = v.dxf.location
                coords.append(pt((loc.x, loc.y, getattr(loc, "z", 0.0))))
            except AttributeError:
                continue
        if not coords:
            return None
        is_closed = bool(entity.dxf.hasattr("flags") and entity.dxf.flags & 1)
        if is_closed and len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            return {"type": "Feature", "properties": {**props, "closed": True},
                    "geometry": {"type": "Polygon", "coordinates": [coords]}}
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "LineString", "coordinates": coords}}
    if kind == "CIRCLE":
        c = entity.dxf.center
        r = float(entity.dxf.radius)
        coords = _circle_coords(c.x, c.y, getattr(c, "z", 0.0), r, transform, segments=64)
        return {"type": "Feature", "properties": {**props, "radius": r},
                "geometry": {"type": "Polygon", "coordinates": [coords]}}
    if kind == "ARC":
        c = entity.dxf.center
        r = float(entity.dxf.radius)
        a0 = math.radians(float(entity.dxf.start_angle))
        a1 = math.radians(float(entity.dxf.end_angle))
        if a1 < a0:
            a1 += 2 * math.pi
        coords = _arc_coords(c.x, c.y, getattr(c, "z", 0.0), r, a0, a1, transform, segments=48)
        return {"type": "Feature", "properties": {**props, "radius": r},
                "geometry": {"type": "LineString", "coordinates": coords}}
    if kind == "TEXT" or kind == "MTEXT":
        try:
            insert = entity.dxf.insert
            text = entity.dxf.text if hasattr(entity.dxf, "text") else entity.text
        except Exception:
            return None
        return {"type": "Feature", "properties": {**props, "text": text},
                "geometry": {"type": "Point", "coordinates": pt(insert)}}
    return None


def _circle_coords(
    cx: float, cy: float, cz: float, r: float,
    transform: Callable[[float, float], tuple[float, float]],
    *, segments: int,
) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(segments + 1):
        ang = 2 * math.pi * i / segments
        x = cx + r * math.cos(ang)
        y = cy + r * math.sin(ang)
        tx, ty = transform(x, y)
        out.append([tx, ty, cz])
    return out


def _arc_coords(
    cx: float, cy: float, cz: float, r: float, a0: float, a1: float,
    transform: Callable[[float, float], tuple[float, float]],
    *, segments: int,
) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(segments + 1):
        ang = a0 + (a1 - a0) * (i / segments)
        x = cx + r * math.cos(ang)
        y = cy + r * math.sin(ang)
        tx, ty = transform(x, y)
        out.append([tx, ty, cz])
    return out


# ── LAS / LAZ ───────────────────────────────────────────────────────────────


# AutoCAD-friendly classification → display colour (LAS classes per ASPRS LAS 1.4 spec).
_LAS_CLASS_COLORS: dict[int, str] = {
    0: "#888888",   # Created, never classified
    1: "#cccccc",   # Unclassified
    2: "#a86b3c",   # Ground
    3: "#3ee8a3",   # Low vegetation
    4: "#3ee8a3",   # Medium vegetation
    5: "#1a7b4a",   # High vegetation
    6: "#ff9c5a",   # Building
    7: "#ff6b6b",   # Low point (noise)
    9: "#3aa1ff",   # Water
    10: "#888888",  # Rail
    11: "#aaaaaa",  # Road surface
    13: "#cccccc",  # Wire-Guard (Shield)
    14: "#cccccc",  # Wire-Conductor (Phase)
    15: "#cccccc",  # Transmission Tower
    16: "#cccccc",  # Wire-structure Connector (e.g. Insulator)
    17: "#888888",  # Bridge Deck
    18: "#ff6b6b",  # High Noise
}


def import_xyz(
    data: bytes,
    *,
    source_crs_epsg: int | None = None,
    z_units: str = "auto",
    max_points: int = 500_000,
    build_mesh: bool = True,
) -> ImportResult:
    """Parse ASCII X Y Z bytes (space- or comma-separated) into a colourable
    point cloud feature.

    The file must have at least three numeric columns per line; extra columns
    are ignored. Lines starting with ``#`` or ``;`` are treated as comments.

    ``source_crs_epsg`` projects the X/Y to WGS84 lon/lat. For US bathymetric
    surveys this is typically a State Plane zone — e.g. **EPSG:2236** for
    Florida East NAD83 (US ft). If omitted, X/Y is assumed already to be
    lon/lat and passed through verbatim.

    ``z_units`` is ``"ft"``, ``"m"``, or ``"auto"`` (default). Auto-detection
    looks at the absolute value range and assumes feet if any value exceeds
    100, otherwise metres. The output ``z_values`` are always converted to
    metres so the client can render consistently.

    Returns a single ``MultiPoint`` feature whose ``properties.z_values``
    array parallels ``geometry.coordinates`` — the client uses this for
    *live* depth-ramp recolouring (no re-upload required).
    """
    text = data.decode("utf-8", errors="replace")
    rows: list[tuple[float, float, float]] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s[0] in "#;":
            continue
        parts = s.replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
        except ValueError:
            continue
        rows.append((x, y, z))

    if not rows:
        raise ValueError("XYZ file has no parsable rows.")

    n_total = len(rows)
    stride = max(1, n_total // max_points)
    rows = rows[::stride]

    # Auto-detect Z units. The file rarely tells us explicitly so we use two
    # signals: (1) if X/Y are huge (typical of US ftUS State Plane), the
    # author was almost certainly working in US feet end-to-end, so Z is too;
    # (2) Z magnitude — values > 100 strongly imply feet for a NAVD88 survey.
    # Caller can override with z_units="ft" or "m" to be explicit.
    if z_units == "auto":
        sample_xy = max(abs(rows[0][0]), abs(rows[0][1]))
        zmag = max(abs(r[2]) for r in rows)
        if sample_xy > 50_000:
            z_units = "ft"   # State Plane / large local coords → ftUS context
        elif zmag > 100:
            z_units = "ft"
        else:
            z_units = "m"
    z_to_m = 0.3048 if z_units == "ft" else 1.0

    transform = _make_transform(source_crs_epsg)

    coords: list[list[float]] = []
    z_values: list[float] = []
    for x, y, z in rows:
        lon, lat = transform(float(x), float(y))
        z_m = z * z_to_m
        coords.append([lon, lat, z_m])
        z_values.append(z_m)

    z_min = min(z_values)
    z_max = max(z_values)

    # Triangulate via Delaunay so the client can render a real TIN surface
    # mesh (HYPACK-style) instead of dotty point clouds. For a regular grid
    # this gives the textbook smooth shaded surface.
    triangles: list[list[int]] = []
    _mesh_warning: str | None = None
    if build_mesh and len(coords) >= 3:
        try:
            import numpy as np
            from scipy.spatial import Delaunay

            xy = np.array([(c[0], c[1]) for c in coords])
            tri = Delaunay(xy)
            triangles = tri.simplices.tolist()
        except Exception as exc:
            # Surface the failure as a warning rather than swallowing — the
            # client can still render points-only mode.
            triangles = []
            _mesh_warning = f"TIN mesh skipped: {exc}"

    feature = {
        "type": "Feature",
        "properties": {
            "format": "xyz",
            "kept": len(coords),
            "total": n_total,
            "stride": stride,
            "z_min_m": z_min,
            "z_max_m": z_max,
            "z_unit_in": z_units,
            "z_unit_out": "m",
            "z_values": z_values,
            "triangles": triangles,
        },
        "geometry": {"type": "MultiPoint", "coordinates": coords},
    }

    bbox = [
        min(c[0] for c in coords), min(c[1] for c in coords), z_min,
        max(c[0] for c in coords), max(c[1] for c in coords), z_max,
    ]

    return ImportResult(
        feature_collection={"type": "FeatureCollection", "features": [feature]},
        summary={
            "format": "xyz",
            "point_count": n_total,
            "kept": len(coords),
            "stride": stride,
            "bbox": bbox,
            "z_min_m": z_min,
            "z_max_m": z_max,
            "z_unit_detected": z_units,
            "source_crs_epsg": source_crs_epsg,
            "triangle_count": len(triangles),
            "has_mesh": len(triangles) > 0,
        },
        warnings=tuple(w for w in (_mesh_warning,) if w),
    )


def import_las(
    data: bytes,
    *,
    source_crs_epsg: int | None = None,
    max_points: int = 200_000,
) -> ImportResult:
    """Parse LAS/LAZ bytes into a sub-sampled GeoJSON MultiPoint.

    The viewer renders these via Cesium PointPrimitive — far cheaper than
    streaming 3D Tiles for a single drag-drop. For datasets larger than
    ``max_points``, every Nth point is kept (deterministic stride).
    Per-point ``classification`` and ``intensity`` attributes are returned
    parallel arrays alongside the coordinates so the viewer can colour by
    class without re-walking the cloud.
    """
    import laspy

    try:
        las = laspy.read(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"LAS/LAZ parse failed: {exc}") from exc

    n_total = int(las.header.point_count)
    if n_total == 0:
        return ImportResult(
            feature_collection={"type": "FeatureCollection", "features": []},
            summary={"format": "las", "point_count": 0},
            warnings=("Point cloud is empty.",),
        )
    stride = max(1, n_total // max_points)
    transform = _make_transform(source_crs_epsg)

    xs = las.x[::stride]
    ys = las.y[::stride]
    zs = las.z[::stride]
    cls = getattr(las, "classification", None)
    intensity = getattr(las, "intensity", None)
    cls_arr = list(cls[::stride]) if cls is not None else [1] * len(xs)
    int_arr = list(intensity[::stride]) if intensity is not None else [0] * len(xs)

    coords: list[list[float]] = []
    classifications: list[int] = []
    intensities: list[int] = []
    colors: list[str] = []
    for i in range(len(xs)):
        x, y = transform(float(xs[i]), float(ys[i]))
        z = float(zs[i])
        coords.append([x, y, z])
        c = int(cls_arr[i])
        classifications.append(c)
        intensities.append(int(int_arr[i]))
        colors.append(_LAS_CLASS_COLORS.get(c, "#cccccc"))

    feature = {
        "type": "Feature",
        "properties": {
            "format": "las",
            "kept": len(coords),
            "total": n_total,
            "stride": stride,
            "classifications": classifications,
            "intensities": intensities,
            "colors": colors,
        },
        "geometry": {"type": "MultiPoint", "coordinates": coords},
    }

    bbox = [
        float(las.header.mins[0]), float(las.header.mins[1]), float(las.header.mins[2]),
        float(las.header.maxs[0]), float(las.header.maxs[1]), float(las.header.maxs[2]),
    ]

    return ImportResult(
        feature_collection={"type": "FeatureCollection", "features": [feature]},
        summary={
            "format": "las",
            "point_count": n_total,
            "kept": len(coords),
            "stride": stride,
            "bbox": bbox,
            "classification_histogram": _histogram(classifications),
        },
    )


def _histogram(values: list[int]) -> dict[str, int]:
    out: dict[int, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return {str(k): v for k, v in sorted(out.items())}


# ── LandXML ─────────────────────────────────────────────────────────────────


def import_landxml(
    data: bytes,
    *,
    source_crs_epsg: int | None = None,
) -> ImportResult:
    """Parse LandXML bytes (Surveyor / civil-3D exchange format).

    Pulls TIN surfaces (each face → ``Polygon``) and parcels (closed ring →
    ``Polygon``). Civil-3D ``Alignment`` and ``Profile`` elements are
    deferred to a future iteration — drag-drop is enough to start with.
    """
    transform = _make_transform(source_crs_epsg)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"LandXML parse failed: {exc}") from exc

    ns = _strip_ns(root)
    features: list[dict[str, Any]] = []
    surface_count = 0
    parcel_count = 0

    # Surfaces.
    for surface in root.iter("Surface"):
        name = surface.get("name", "")
        defn = surface.find("Definition")
        if defn is None:
            continue
        # Build a {pnt_id: (x, y, z)} dict.
        points: dict[str, tuple[float, float, float]] = {}
        for p in defn.iter("P"):
            pid = p.get("id", "")
            try:
                parts = (p.text or "").split()
                if len(parts) >= 3:
                    # LandXML order is N E Z (north, east, elevation).
                    n_, e_, z = float(parts[0]), float(parts[1]), float(parts[2])
                    x, y = transform(e_, n_)
                    points[pid] = (x, y, z)
            except ValueError:
                continue
        # Faces reference 3 point ids.
        for f in defn.iter("F"):
            ids = (f.text or "").split()
            if len(ids) < 3:
                continue
            ring: list[list[float]] = []
            try:
                for pid in ids:
                    if pid in points:
                        ring.append(list(points[pid]))
                if len(ring) < 3:
                    continue
                ring.append(ring[0])
                features.append({
                    "type": "Feature",
                    "properties": {"layer": f"surface:{name}", "kind": "tin_face"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                })
            except KeyError:
                continue
        surface_count += 1

    # Parcels.
    for parcel in root.iter("Parcel"):
        name = parcel.get("name", "")
        coordgeom = parcel.find("CoordGeom") or parcel.find("Center")
        # mypy: re-bind the same name; intentional in this file.
        ring = []
        # Try CoordGeom > Line > Start/End first.
        if coordgeom is not None:
            for line in coordgeom.iter("Line"):
                for which in ("Start", "End"):
                    el = line.find(which)
                    if el is None or el.text is None:
                        continue
                    parts = el.text.split()
                    if len(parts) >= 2:
                        n_, e_ = float(parts[0]), float(parts[1])
                        z = float(parts[2]) if len(parts) >= 3 else 0.0
                        x, y = transform(e_, n_)
                        if not ring or ring[-1] != [x, y, z]:
                            ring.append([x, y, z])
        if len(ring) >= 3:
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            features.append({
                "type": "Feature",
                "properties": {"layer": "parcels", "name": name},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
            parcel_count += 1

    return ImportResult(
        feature_collection={"type": "FeatureCollection", "features": features},
        summary={
            "format": "landxml",
            "surface_count": surface_count,
            "parcel_count": parcel_count,
            "feature_count": len(features),
            "namespace": ns,
        },
    )


def _strip_ns(root: ET.Element) -> str:
    """Strip the LandXML namespace so we can look up tags by short name."""
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0][1:]
        for el in root.iter():
            if el.tag.startswith("{"):
                el.tag = el.tag.split("}", 1)[1]
    return ns


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_transform(source_epsg: int | None) -> Callable[[float, float], tuple[float, float]]:
    """Return an (x, y) → (x, y) projection function.

    If ``source_epsg`` is given and pyproj is available, returns a function
    that projects to EPSG:4326 (WGS84). Otherwise returns the identity — the
    caller is asserting the file is already in lon/lat.
    """
    if source_epsg is None or source_epsg == 4326:
        return lambda x, y: (x, y)
    try:
        from pyproj import Transformer

        t = Transformer.from_crs(source_epsg, 4326, always_xy=True)
        return lambda x, y: t.transform(x, y)
    except Exception:
        return lambda x, y: (x, y)


def _features_bbox(features: list[dict[str, Any]]) -> list[float] | None:
    if not features:
        return None
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for f in features:
        geom = f.get("geometry") or {}
        for x, y, *_ in _iter_geom_points(geom):
            minx = min(minx, x)
            miny = min(miny, y)
            maxx = max(maxx, x)
            maxy = max(maxy, y)
    if minx == float("inf"):
        return None
    return [minx, miny, maxx, maxy]


def _iter_geom_points(geom: dict[str, Any]) -> Iterator[list[float]]:
    t = geom.get("type")
    coords = geom.get("coordinates")
    if coords is None:
        return
    if t == "Point":
        yield coords
    elif t in ("MultiPoint", "LineString"):
        yield from coords
    elif t in ("MultiLineString", "Polygon"):
        for ring in coords:
            yield from ring
    elif t == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                yield from ring


# ── Format dispatch ─────────────────────────────────────────────────────────


def detect_and_import(
    filename: str, data: bytes, *, source_crs_epsg: int | None = None,
) -> ImportResult:
    """Pick the right importer based on filename extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "dxf":
        return import_dxf(data, source_crs_epsg=source_crs_epsg)
    if ext in ("las", "laz"):
        return import_las(data, source_crs_epsg=source_crs_epsg)
    if ext in ("xml", "landxml"):
        return import_landxml(data, source_crs_epsg=source_crs_epsg)
    if ext in ("xyz", "txt", "asc"):
        return import_xyz(data, source_crs_epsg=source_crs_epsg)
    raise ValueError(
        f"Unsupported geofile extension '.{ext}'. "
        "Supported: .dxf, .las, .laz, .xml/.landxml, .xyz/.txt/.asc."
    )


__all__ = [
    "ImportResult",
    "detect_and_import",
    "import_dxf",
    "import_landxml",
    "import_las",
    "import_xyz",
]
