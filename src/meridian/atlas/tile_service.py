"""Atlas tile service — streams the canonical Survey model to CesiumJS.

A FastAPI app that serves:

* ``/api/health``                       — liveness check
* ``/api/projects``                     — projects in the active DB
* ``/api/parcels.geojson``              — every parcel as a GeoJSON FeatureCollection
* ``/api/parcel/{id}.geojson``          — one parcel
* ``/api/cloud/{id}.copc.laz``          — range-request streaming of a registered LAZ
* ``/atlas/``                           — the Cesium HTML viewer
* ``/atlas/static/...``                 — bundled CesiumJS + the viewer JS

The viewer talks back to the Python desktop via QWebChannel; the same
HTTP endpoints are also reachable from a real browser, so future web /
mobile clients can use them unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from meridian.atlas.bookmarks import BookmarkStore
from meridian.atlas.edit_session import EditSession, measure_segments
from meridian.atlas.geofile_import import detect_and_import
from meridian.atlas.presentations import (
    AssetRegistry,
    CameraState,
    LayerState,
    Presentation,
    PresentationStore,
    Scene,
    SceneAnnotation,
    curated_catalog,
)

if TYPE_CHECKING:
    from meridian.ports.repository import (
        ParcelRepository,
        PointCloudRepository,
        SurveyRepository,
    )


def create_app(
    *,
    survey_repo: SurveyRepository | None = None,
    parcel_repo: ParcelRepository | None = None,
    cloud_repo: PointCloudRepository | None = None,
    static_dir: Path | None = None,
    cesium_ion_token: str | None = None,
    google_maps_key: str | None = None,
    edit_session: EditSession | None = None,
    presentation_store: PresentationStore | None = None,
    asset_registry: AssetRegistry | None = None,
    bookmark_store: BookmarkStore | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to the supplied repositories.

    All repositories default to ``None`` so the app can boot in
    "demo mode" with a single hard-coded sample parcel — useful for
    showcasing Atlas without a populated project DB.

    ``edit_session`` is the in-memory editable scene that backs the
    interactive viewer (draw / edit / split / merge / delete). If omitted, a
    fresh session is created so demo mode is fully interactive.
    """
    app = FastAPI(title="Meridian Atlas Tile Service", version="0.1.0")
    static_dir = static_dir or (Path(__file__).parent / "static")
    if static_dir.exists():
        app.mount("/atlas/static", StaticFiles(directory=str(static_dir)), name="atlas_static")

    session = edit_session if edit_session is not None else EditSession()
    app.state.edit_session = session
    presentations = presentation_store if presentation_store is not None else PresentationStore()
    assets = asset_registry if asset_registry is not None else AssetRegistry()
    bookmarks = bookmark_store if bookmark_store is not None else BookmarkStore()
    app.state.presentation_store = presentations
    app.state.asset_registry = assets
    app.state.bookmark_store = bookmarks

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "meridian.atlas",
            "demo_mode": survey_repo is None,
            "ion_configured": cesium_ion_token is not None,
            "google_maps_configured": google_maps_key is not None,
        }

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, Any]]:
        if survey_repo is None:
            return [{"id": "demo", "name": "Demo (no project DB attached)"}]
        return [
            {"id": p.id, "name": p.name, "client": p.client, "location": p.location}
            for p in survey_repo.list_projects()
        ]

    @app.get("/api/parcels.geojson")
    async def parcels_geojson(project_id: str | None = None) -> JSONResponse:
        if survey_repo is None:
            return JSONResponse(_demo_parcels_geojson())
        # Iterate projects → surveys → parcels, build a single FC.
        features: list[dict[str, Any]] = []
        projects = (
            [survey_repo.get_project(project_id)] if project_id else list(survey_repo.list_projects())
        )
        from meridian.adapters.gis.geojson import _parcel_props, _ring_to_wgs84
        for project in projects:
            if project is None:
                continue
            for survey in project.surveys:
                for parcel in survey.parcels:
                    if parcel.boundary is None:
                        continue
                    ring = _ring_to_wgs84(parcel.boundary.polygon.exterior, parcel.crs)
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"{project.id}:{survey.id}:{parcel.name}",
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                            "properties": _parcel_props(parcel),
                        }
                    )
        return JSONResponse({"type": "FeatureCollection", "features": features})

    @app.get("/api/cloud/{cloud_id}.copc.laz", response_model=None)
    async def cloud_stream(cloud_id: str, request: Request) -> StreamingResponse:
        if cloud_repo is None:
            raise HTTPException(404, "No point-cloud repository configured.")
        # Look up the cloud across surveys (linear; v0.6 indexes properly).
        path: Path | None = None
        if survey_repo is not None:
            for project in survey_repo.list_projects():
                for survey in project.surveys:
                    for cloud in cloud_repo.list_for_survey(survey.id):
                        if cloud.path.stem == cloud_id:
                            path = cloud.path
                            break
        if path is None or not path.exists():
            raise HTTPException(404, f"Cloud {cloud_id!r} not found.")
        return _serve_range(request, path)

    # ── Interactive editing endpoints ──────────────────────────────────────
    #
    # These power the Atlas viewer's draw / edit / split / merge / delete
    # tools. They operate on the in-memory :class:`EditSession`; nothing is
    # persisted to a project DB unless the caller explicitly migrates the
    # session into one (a v0.7 task).

    @app.get("/api/session/parcels.geojson")
    async def session_parcels() -> JSONResponse:
        return JSONResponse(session.to_geojson())

    @app.post("/api/session/parcels", status_code=201)
    async def session_create_parcel(payload: _CreateParcel) -> JSONResponse:
        try:
            feature = session.create_parcel(payload.ring, payload.properties)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(feature, status_code=201)

    @app.put("/api/session/parcels/{parcel_id}/geometry")
    async def session_update_geometry(parcel_id: str, payload: _UpdateGeometry) -> JSONResponse:
        try:
            return JSONResponse(session.update_parcel_geometry(parcel_id, payload.ring))
        except KeyError as exc:
            raise HTTPException(404, f"Parcel {parcel_id!r} not found.") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/session/parcels/{parcel_id}/properties")
    async def session_update_properties(parcel_id: str, payload: _UpdateProperties) -> JSONResponse:
        try:
            return JSONResponse(session.update_parcel_properties(parcel_id, payload.properties))
        except KeyError as exc:
            raise HTTPException(404, f"Parcel {parcel_id!r} not found.") from exc

    @app.delete("/api/session/parcels/{parcel_id}", status_code=204)
    async def session_delete(parcel_id: str) -> None:
        try:
            session.delete_parcel(parcel_id)
        except KeyError as exc:
            raise HTTPException(404, f"Parcel {parcel_id!r} not found.") from exc

    @app.post("/api/session/parcels/{parcel_id}/split")
    async def session_split(parcel_id: str, payload: _SplitRequest) -> JSONResponse:
        try:
            left, right = session.split_parcel(
                parcel_id,
                cut=(payload.cut_from, payload.cut_to),
                left_name=payload.left_name,
                right_name=payload.right_name,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse({"left": left, "right": right})

    @app.post("/api/session/merge")
    async def session_merge(payload: _MergeRequest) -> JSONResponse:
        try:
            return JSONResponse(session.merge_parcels(payload.parcel_ids, name=payload.name))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/session/clear", status_code=204)
    async def session_clear() -> None:
        session.clear()

    @app.post("/api/session/measure")
    async def measure(payload: _MeasureRequest) -> JSONResponse:
        if len(payload.positions) < 2:
            raise HTTPException(400, "Need at least 2 positions to measure.")
        return JSONResponse(measure_segments(payload.positions))

    @app.get("/api/session/snap")
    async def session_snap(lon: float, lat: float, tolerance_m: float = 1.0) -> JSONResponse:
        result = session.snap_lonlat(lon, lat, tolerance_m=tolerance_m)
        return JSONResponse({"hit": result is not None, "node": result})

    # ── CoGo (Coordinate Geometry) ────────────────────────────────────────
    # All CoGo endpoints use pyproj.Geod on the WGS84 ellipsoid for
    # geodesically-correct results. Survey-grade for parcel-scale work; for
    # state-plane projection-aware work, use the math.cogo + transforms
    # combo via the CLI for now.

    @app.post("/api/cogo/forward")
    async def cogo_forward(payload: _CogoForwardRequest) -> JSONResponse:
        from pyproj import Geod
        g = Geod(ellps="WGS84")
        # pyproj.Geod.fwd takes azimuth in degrees clockwise from north —
        # matches surveyor convention.
        out_lon, out_lat, back_az = g.fwd(payload.lon, payload.lat, payload.bearing_deg, payload.distance_m)
        # Normalize back-azimuth to [0, 360)
        back_az = (back_az + 360.0) % 360.0
        return JSONResponse({
            "lon": float(out_lon),
            "lat": float(out_lat),
            "back_bearing_deg": float(back_az),
            "input_bearing_deg": float(payload.bearing_deg),
            "input_distance_m": float(payload.distance_m),
        })

    @app.post("/api/cogo/inverse")
    async def cogo_inverse(payload: _CogoInverseRequest) -> JSONResponse:
        from pyproj import Geod
        if len(payload.p1) != 2 or len(payload.p2) != 2:
            raise HTTPException(400, "Each point must be [lon, lat].")
        g = Geod(ellps="WGS84")
        fwd_az, back_az, dist_m = g.inv(payload.p1[0], payload.p1[1], payload.p2[0], payload.p2[1])
        return JSONResponse({
            "distance_m": float(dist_m),
            "forward_bearing_deg": float((fwd_az + 360.0) % 360.0),
            "back_bearing_deg": float((back_az + 360.0) % 360.0),
        })

    @app.post("/api/cogo/traverse")
    async def cogo_traverse(payload: _CogoTraverseRequest) -> JSONResponse:
        """Walk a closed traverse on the WGS84 ellipsoid.

        Returns the raw polyline of computed endpoints, plus closure analysis
        (distance / bearing back to start, perimeter, ratio, area). Compass-rule
        adjustment distributes closure error proportionally to leg distance.
        """
        from pyproj import Geod

        if len(payload.start) != 2:
            raise HTTPException(400, "start must be [lon, lat].")
        if payload.adjustment not in {"none", "compass"}:
            raise HTTPException(400, "adjustment must be 'none' or 'compass'.")

        g = Geod(ellps="WGS84")
        # Walk legs geodesically.
        pts: list[list[float]] = [[payload.start[0], payload.start[1]]]
        for leg in payload.legs:
            prev_lon, prev_lat = pts[-1]
            out_lon, out_lat, _back = g.fwd(prev_lon, prev_lat, leg.bearing_deg, leg.distance_m)
            pts.append([float(out_lon), float(out_lat)])

        # Closure analysis — geodesic distance from last computed point back to
        # the start. For a perfectly-closed survey this is zero.
        last = pts[-1]
        closure_fwd_az, _closure_back_az, closure_dist_m = g.inv(
            last[0], last[1], payload.start[0], payload.start[1]
        )
        perimeter_m = float(sum(leg.distance_m for leg in payload.legs))
        closure_ratio = float("inf") if closure_dist_m < 1e-9 else perimeter_m / float(closure_dist_m)

        # Geodesic polygon area via Geod.geometry_area_perimeter (signed,
        # positive for CCW). We pass the closed ring (append start at the end
        # so pyproj treats it as a closed polygon). Returns (area_m2, perim_m);
        # we already have perim_m from the leg sum so just take the area.
        ring_lons = [p[0] for p in pts] + [payload.start[0]]
        ring_lats = [p[1] for p in pts] + [payload.start[1]]
        try:
            area_m2_signed, _ = g.polygon_area_perimeter(ring_lons, ring_lats)
        except Exception:
            area_m2_signed = 0.0

        adjusted_pts = pts
        if payload.adjustment == "compass" and closure_dist_m > 1e-9:
            # Compass (Bowditch) adjustment in geodesic-approximate form:
            # distribute closure correction across legs proportionally to
            # cumulative distance. Apply correction in lat/lon offset directly
            # — fine for parcel-scale traverses.
            closure_dlon = payload.start[0] - last[0]
            closure_dlat = payload.start[1] - last[1]
            adjusted_pts = [pts[0][:]]
            cum = 0.0
            for i, leg in enumerate(payload.legs):
                cum += leg.distance_m
                frac = cum / perimeter_m
                base = pts[i + 1]
                adjusted_pts.append([
                    float(base[0] + closure_dlon * frac),
                    float(base[1] + closure_dlat * frac),
                ])

        return JSONResponse({
            "raw_points": pts,
            "adjusted_points": adjusted_pts,
            "closure_distance_m": float(closure_dist_m),
            "closure_bearing_deg": float((closure_fwd_az + 360.0) % 360.0),
            "closure_ratio": closure_ratio,
            "perimeter_m": perimeter_m,
            "area_m2": float(abs(area_m2_signed)),
            "adjustment": payload.adjustment,
        })

    # ── 3D asset registry ──────────────────────────────────────────────────

    @app.get("/api/assets/catalog")
    async def assets_catalog() -> JSONResponse:
        """Curated Cesium ion terrain + 3D-Tiles starter catalog."""
        return JSONResponse(curated_catalog())

    @app.get("/api/assets")
    async def assets_list() -> JSONResponse:
        return JSONResponse(assets.to_json())

    @app.post("/api/assets/tilesets", status_code=201)
    async def assets_add_tileset(payload: _AddTilesetRequest) -> JSONResponse:
        from dataclasses import asdict as _asdict
        asset = assets.add_tileset(payload.label, payload.source, color=payload.color)
        return JSONResponse(_asdict(asset), status_code=201)

    @app.delete("/api/assets/tilesets/{asset_id}", status_code=204)
    async def assets_remove_tileset(asset_id: str) -> None:
        try:
            assets.remove_tileset(asset_id)
        except KeyError as exc:
            raise HTTPException(404, f"Tileset {asset_id!r} not found.") from exc

    @app.post("/api/assets/models", status_code=201)
    async def assets_add_model(payload: _AddModelRequest) -> JSONResponse:
        from dataclasses import asdict as _asdict
        asset = assets.add_model(
            payload.label, payload.url,
            lon=payload.lon, lat=payload.lat, height=payload.height,
            heading_deg=payload.heading_deg, scale=payload.scale,
        )
        return JSONResponse(_asdict(asset), status_code=201)

    @app.delete("/api/assets/models/{asset_id}", status_code=204)
    async def assets_remove_model(asset_id: str) -> None:
        try:
            assets.remove_model(asset_id)
        except KeyError as exc:
            raise HTTPException(404, f"Model {asset_id!r} not found.") from exc

    # ── Presentation library ───────────────────────────────────────────────

    @app.get("/api/presentations")
    async def presentations_list() -> JSONResponse:
        return JSONResponse(presentations.list())

    @app.get("/api/presentations/{presentation_id}")
    async def presentation_get(presentation_id: str) -> JSONResponse:
        try:
            p = presentations.get(presentation_id)
        except KeyError as exc:
            raise HTTPException(404, f"Presentation {presentation_id!r} not found.") from exc
        return JSONResponse(_presentation_to_dict(p))

    @app.post("/api/presentations", status_code=201)
    async def presentation_create(payload: _PresentationPayload) -> JSONResponse:
        p = _presentation_from_payload(payload)
        saved = presentations.save(p)
        return JSONResponse(_presentation_to_dict(saved), status_code=201)

    @app.put("/api/presentations/{presentation_id}")
    async def presentation_update(presentation_id: str, payload: _PresentationPayload) -> JSONResponse:
        try:
            existing = presentations.get(presentation_id)
        except KeyError as exc:
            raise HTTPException(404, f"Presentation {presentation_id!r} not found.") from exc
        next_p = _presentation_from_payload(payload)
        # Preserve creation timestamp; PresentationStore.save bumps updated_at.
        next_p_with_id = Presentation(
            id=existing.id, title=next_p.title or existing.title,
            description=next_p.description, scenes=next_p.scenes,
            created_at=existing.created_at, updated_at=existing.updated_at,
            author=next_p.author or existing.author,
        )
        saved = presentations.save(next_p_with_id)
        return JSONResponse(_presentation_to_dict(saved))

    @app.delete("/api/presentations/{presentation_id}", status_code=204)
    async def presentation_delete(presentation_id: str) -> None:
        try:
            presentations.delete(presentation_id)
        except KeyError as exc:
            raise HTTPException(404, f"Presentation {presentation_id!r} not found.") from exc

    # ── Geofile import (DXF / LAS / LAZ / LandXML) ────────────────────────

    @app.post("/api/geofile/import")
    async def geofile_import(
        request: Request,
        filename: str,
        source_epsg: int | None = None,
    ) -> JSONResponse:
        """Stream a binary geofile body, parse server-side, return GeoJSON.

        ``filename`` is a query parameter rather than a multipart upload to
        keep the wire format trivial; the body is the raw file bytes.
        """
        body = await request.body()
        if not body:
            raise HTTPException(400, "Empty body — POST the file bytes.")
        try:
            result = detect_and_import(filename, body, source_crs_epsg=source_epsg)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(result.to_json())

    # ── Bookmarks ──────────────────────────────────────────────────────────

    @app.get("/api/bookmarks")
    async def bookmarks_list() -> JSONResponse:
        from dataclasses import asdict as _asdict
        return JSONResponse([
            {
                "id": b.id, "title": b.title, "description": b.description,
                "clock_iso": b.clock_iso, "created_at": b.created_at,
                "tags": list(b.tags),
                "camera": _asdict(b.camera),
                "layers": _asdict(b.layers),
            } for b in bookmarks.list()
        ])

    @app.post("/api/bookmarks", status_code=201)
    async def bookmarks_create(payload: _BookmarkPayload) -> JSONResponse:
        from dataclasses import asdict as _asdict

        cam = CameraState(
            lon=payload.camera.lon, lat=payload.camera.lat, height=payload.camera.height,
            heading_deg=payload.camera.heading_deg, pitch_deg=payload.camera.pitch_deg,
            roll_deg=payload.camera.roll_deg,
        )
        layers = LayerState(
            terrain_kind=payload.layers.terrain_kind,
            imagery_visible=tuple(payload.layers.imagery_visible),
            imagery_alpha=tuple(payload.layers.imagery_alpha),
            tilesets=tuple(payload.layers.tilesets),
            models=tuple(payload.layers.models),
            show_atmosphere=payload.layers.show_atmosphere,
            show_sun=payload.layers.show_sun,
            show_stars=payload.layers.show_stars,
            show_lighting=payload.layers.show_lighting,
        ) if payload.layers else LayerState()
        bm = bookmarks.create(
            title=payload.title or "Bookmark",
            description=payload.description, camera=cam, layers=layers,
            clock_iso=payload.clock_iso, tags=tuple(payload.tags),
        )
        return JSONResponse({
            "id": bm.id, "title": bm.title, "description": bm.description,
            "clock_iso": bm.clock_iso, "created_at": bm.created_at,
            "tags": list(bm.tags),
            "camera": _asdict(bm.camera),
            "layers": _asdict(bm.layers),
        }, status_code=201)

    @app.delete("/api/bookmarks/{bookmark_id}", status_code=204)
    async def bookmarks_delete(bookmark_id: str) -> None:
        try:
            bookmarks.delete(bookmark_id)
        except KeyError as exc:
            raise HTTPException(404, f"Bookmark {bookmark_id!r} not found.") from exc

    @app.get("/atlas/", response_class=HTMLResponse)
    async def atlas_page() -> HTMLResponse:
        index = static_dir / "index.html"
        if index.exists():
            html = index.read_text(encoding="utf-8")
        else:
            html = _bootstrap_html()
        # Inject ion token + maps key as script-globals (read by viewer.js).
        html = html.replace(
            "<!--MERIDIAN_CONFIG-->",
            f"<script>window.MERIDIAN_CONFIG={{ionToken:{json.dumps(cesium_ion_token)},googleMapsKey:{json.dumps(google_maps_key)}}};</script>",
        )
        return HTMLResponse(html)

    return app


class _CreateParcel(BaseModel):
    ring: list[list[float]] = Field(..., description="Ordered [lon, lat] pairs (open or closed).")
    properties: dict[str, Any] | None = None


class _UpdateGeometry(BaseModel):
    ring: list[list[float]]


class _UpdateProperties(BaseModel):
    properties: dict[str, Any]


class _SplitRequest(BaseModel):
    cut_from: list[float] = Field(..., min_length=2, max_length=3)
    cut_to: list[float] = Field(..., min_length=2, max_length=3)
    left_name: str = ""
    right_name: str = ""


class _MergeRequest(BaseModel):
    parcel_ids: list[str] = Field(..., min_length=2)
    name: str = ""


class _MeasureRequest(BaseModel):
    positions: list[list[float]] = Field(..., description="Ordered [lon, lat] pairs.")


class _CogoForwardRequest(BaseModel):
    """Inputs for a CoGo forward computation: project a point along a bearing."""

    lon: float
    lat: float
    bearing_deg: float = Field(..., description="Azimuth in degrees, clockwise from true north.")
    distance_m: float = Field(..., gt=0, description="Geodesic distance in metres.")


class _CogoInverseRequest(BaseModel):
    """Inputs for a CoGo inverse computation: distance + bearing between 2 points."""

    p1: list[float] = Field(..., description="[lon, lat]")
    p2: list[float] = Field(..., description="[lon, lat]")


class _TraverseLeg(BaseModel):
    """One leg of a traverse — bearing + distance from the previous point."""

    bearing_deg: float = Field(..., description="Azimuth in degrees, clockwise from north.")
    distance_m: float = Field(..., gt=0, description="Geodesic distance in metres.")


class _CogoTraverseRequest(BaseModel):
    """Inputs for a closed-traverse computation."""

    start: list[float] = Field(..., description="[lon, lat] of the starting point.")
    legs: list[_TraverseLeg] = Field(..., min_length=1, description="Ordered legs from start.")
    adjustment: str = Field(
        default="none",
        description="'none' | 'compass' (Bowditch). Compass rule distributes closure error proportional to leg distance.",
    )


class _AddTilesetRequest(BaseModel):
    label: str
    source: str = Field(..., description="Either 'ion:<asset-id>' or a tileset.json URL.")
    color: str | None = None


class _AddModelRequest(BaseModel):
    label: str
    url: str
    lon: float
    lat: float
    height: float = 0.0
    heading_deg: float = 0.0
    scale: float = 1.0


class _CameraStatePayload(BaseModel):
    lon: float
    lat: float
    height: float
    heading_deg: float = 0.0
    pitch_deg: float = -45.0
    roll_deg: float = 0.0


class _LayerStatePayload(BaseModel):
    terrain_kind: str = "auto"
    imagery_visible: list[bool] = Field(default_factory=list)
    imagery_alpha: list[float] = Field(default_factory=list)
    tilesets: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    show_atmosphere: bool = True
    show_sun: bool = True
    show_stars: bool = True
    show_lighting: bool = False


class _SceneAnnotationPayload(BaseModel):
    kind: str = "label"
    lon: float
    lat: float
    height: float = 0.0
    text: str = ""
    color: str = "#ffd76e"
    extra: dict[str, Any] = Field(default_factory=dict)


class _ScenePayload(BaseModel):
    id: str | None = None
    title: str = ""
    narration: str = ""
    camera: _CameraStatePayload
    layers: _LayerStatePayload = Field(default_factory=_LayerStatePayload)
    fly_duration_s: float = 2.5
    auto_advance_s: float | None = None
    clock_iso: str | None = None
    selected_parcel_id: str | None = None
    annotations: list[_SceneAnnotationPayload] = Field(default_factory=list)


class _BookmarkPayload(BaseModel):
    title: str
    description: str = ""
    camera: _CameraStatePayload
    layers: _LayerStatePayload | None = None
    clock_iso: str | None = None
    tags: list[str] = Field(default_factory=list)


class _PresentationPayload(BaseModel):
    id: str | None = None
    title: str
    description: str = ""
    scenes: list[_ScenePayload] = Field(default_factory=list)
    author: str = ""


def _presentation_from_payload(p: _PresentationPayload) -> Presentation:
    import uuid as _uuid

    pid = p.id or f"p_{_uuid.uuid4().hex[:10]}"
    scenes: list[Scene] = []
    for s in p.scenes:
        scenes.append(
            Scene(
                id=s.id or f"s_{_uuid.uuid4().hex[:10]}",
                title=s.title, narration=s.narration,
                camera=CameraState(
                    lon=s.camera.lon, lat=s.camera.lat, height=s.camera.height,
                    heading_deg=s.camera.heading_deg, pitch_deg=s.camera.pitch_deg,
                    roll_deg=s.camera.roll_deg,
                ),
                layers=LayerState(
                    terrain_kind=s.layers.terrain_kind,
                    imagery_visible=tuple(s.layers.imagery_visible),
                    imagery_alpha=tuple(s.layers.imagery_alpha),
                    tilesets=tuple(s.layers.tilesets),
                    models=tuple(s.layers.models),
                    show_atmosphere=s.layers.show_atmosphere,
                    show_sun=s.layers.show_sun,
                    show_stars=s.layers.show_stars,
                    show_lighting=s.layers.show_lighting,
                ),
                fly_duration_s=s.fly_duration_s,
                auto_advance_s=s.auto_advance_s,
                clock_iso=s.clock_iso,
                selected_parcel_id=s.selected_parcel_id,
                annotations=tuple(
                    SceneAnnotation(
                        kind=a.kind, lon=a.lon, lat=a.lat, height=a.height,
                        text=a.text, color=a.color, extra=a.extra,
                    ) for a in s.annotations
                ),
            )
        )
    return Presentation(
        id=pid, title=p.title, description=p.description,
        scenes=tuple(scenes), author=p.author,
    )


def _presentation_to_dict(p: Presentation) -> dict[str, Any]:
    from dataclasses import asdict as _asdict

    return {
        "id": p.id, "title": p.title, "description": p.description,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "author": p.author,
        "scenes": [
            {
                "id": s.id, "title": s.title, "narration": s.narration,
                "fly_duration_s": s.fly_duration_s,
                "auto_advance_s": s.auto_advance_s,
                "clock_iso": s.clock_iso,
                "selected_parcel_id": s.selected_parcel_id,
                "camera": _asdict(s.camera),
                "layers": _asdict(s.layers),
                "annotations": [_asdict(a) for a in s.annotations],
            } for s in p.scenes
        ],
    }


def _serve_range(request: Request, path: Path) -> StreamingResponse:
    """Stream a file with HTTP Range support — required by COPC clients."""
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header is None:
        return StreamingResponse(
            iter_file(path, 0, file_size),
            media_type="application/octet-stream",
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )
    # Parse "bytes=START-END"
    try:
        start_str, end_str = range_header.replace("bytes=", "").split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
    except (ValueError, IndexError) as e:
        raise HTTPException(416, "Invalid Range header.") from e
    end = min(end, file_size - 1)
    length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(
        iter_file(path, start, length),
        status_code=206,
        media_type="application/octet-stream",
        headers=headers,
    )


def iter_file(path: Path, start: int, length: int, *, chunk: int = 65536) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _demo_parcels_geojson() -> dict[str, Any]:
    """A single hard-coded parcel near downtown Austin for demos."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "demo:austin",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-97.7444, 30.2672],
                            [-97.7434, 30.2672],
                            [-97.7434, 30.2682],
                            [-97.7444, 30.2682],
                            [-97.7444, 30.2672],
                        ]
                    ],
                },
                "properties": {
                    "name": "Demo parcel — Austin, TX",
                    "area_m2": 11000.0,
                    "perimeter_m": 420.0,
                },
            }
        ],
    }


def _bootstrap_html() -> str:
    """Fallback HTML when ``static/index.html`` is not bundled."""
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Meridian Atlas (bootstrap)</title></head><body>
<h2>Atlas static files are not bundled.</h2>
<p>Place <code>index.html</code> + the CesiumJS bundle in
<code>src/meridian/atlas/static/</code> to enable the viewer.</p>
</body></html>"""
