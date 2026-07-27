"""Interactive 3D geospatial presentations.

A *presentation* is an ordered sequence of *scenes* the viewer can play
back. Each scene is a complete snapshot of the Atlas state — camera
position + orientation, terrain provider, imagery layers, loaded 3D
Tiles assets and glTF models, narration text, sun/time clock, selected
parcel — captured at the moment the user clicks "Capture scene". The
viewer can then step forward/backward through scenes with smooth
camera flights between them, optionally auto-advancing on a timer.

The intended workflow:

1.  Position the camera, load the terrain / imagery / 3D Tiles / glTF
    layers you want, optionally select a parcel for context.
2.  Click "Capture scene" — the entire current state is recorded.
3.  Repeat for as many scenes as the story needs.
4.  Save the presentation; it's persisted to the user data directory and
    can be re-opened, edited, shared as JSON, or played back unattended.

Storage is JSON files under ``platformdirs.user_data_dir("meridian")``
so presentations survive across runs without needing a project DB.
This module also exposes an :class:`AssetRegistry` that tracks 3D Tiles
and glTF assets loaded into the viewer — scenes reference assets by
their registry ID so a presentation can rehydrate them on playback.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

# ── Core records ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CameraState:
    """A snapshot of the camera's pose, expressed in WGS84 lon/lat."""

    lon: float
    lat: float
    height: float
    heading_deg: float = 0.0
    pitch_deg: float = -45.0
    roll_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class LayerState:
    """Which terrain / imagery / 3D-Tiles assets should be active in a scene."""

    terrain_kind: str = "auto"
    """One of: ``"ellipsoid"``, ``"world_terrain"``, ``"bathymetry"``,
    ``"ion:<asset-id>"``, ``"url:<quantized-mesh-url>"``, or ``"auto"`` to
    keep whatever the viewer currently shows."""

    imagery_visible: tuple[bool, ...] = ()
    """Per-imagery-layer visibility flags, in viewer-stack order (bottom-first)."""

    imagery_alpha: tuple[float, ...] = ()
    """Per-imagery-layer alpha (0–1), same order as ``imagery_visible``."""

    tilesets: tuple[str, ...] = ()
    """Asset registry IDs of every 3D-Tiles tileset that should be visible."""

    models: tuple[str, ...] = ()
    """Asset registry IDs of every glTF model that should be visible."""

    show_atmosphere: bool = True
    show_sun: bool = True
    show_stars: bool = True
    show_lighting: bool = False


@dataclass(frozen=True, slots=True)
class SceneAnnotation:
    """A free-form annotation attached to a scene (callout text, arrow, ring)."""

    kind: str            # "label" | "arrow" | "ring" | "polyline"
    lon: float
    lat: float
    height: float = 0.0
    text: str = ""
    color: str = "#ffd76e"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Scene:
    """A single beat of a presentation."""

    id: str
    title: str = ""
    narration: str = ""
    camera: CameraState = field(default_factory=lambda: CameraState(0.0, 0.0, 1_000_000.0))
    layers: LayerState = field(default_factory=LayerState)
    fly_duration_s: float = 2.5
    auto_advance_s: float | None = None
    clock_iso: str | None = None
    """ISO-8601 timestamp the simulation clock should be set to. Drives
    sun position and shadows for solar-easement / shading studies."""
    selected_parcel_id: str | None = None
    annotations: tuple[SceneAnnotation, ...] = ()


@dataclass(frozen=True, slots=True)
class Presentation:
    """A complete narrative — title + ordered scenes + bookkeeping."""

    id: str
    title: str
    description: str = ""
    scenes: tuple[Scene, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    author: str = ""

    def with_scenes(self, scenes: tuple[Scene, ...]) -> Presentation:
        return Presentation(
            id=self.id, title=self.title, description=self.description,
            scenes=scenes, created_at=self.created_at,
            updated_at=_now_iso(), author=self.author,
        )


# ── Asset registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TilesetAsset:
    """A 3D-Tiles tileset known to the viewer."""

    id: str
    label: str
    source: str
    """Either ``"ion:<asset-id>"`` or a full ``https://…/tileset.json`` URL."""
    color: str | None = None
    visible: bool = True


@dataclass(frozen=True, slots=True)
class ModelAsset:
    """A glTF / GLB model anchored to a position."""

    id: str
    label: str
    url: str
    lon: float
    lat: float
    height: float = 0.0
    heading_deg: float = 0.0
    scale: float = 1.0
    visible: bool = True


class AssetRegistry:
    """Catalog of the 3D content that's been added to the viewer.

    The viewer renders directly through Cesium; this registry keeps the
    *server-side* truth for presentation playback. When a scene's
    ``layers.tilesets`` references an asset id that's in the registry,
    the viewer can re-add the corresponding tileset on rehydration.
    """

    def __init__(self) -> None:
        self._tilesets: dict[str, TilesetAsset] = {}
        self._models: dict[str, ModelAsset] = {}
        self._lock = threading.RLock()

    # ── Tilesets ───────────────────────────────────────────────────────────

    def add_tileset(self, label: str, source: str, *, color: str | None = None) -> TilesetAsset:
        with self._lock:
            asset = TilesetAsset(id=f"t_{uuid.uuid4().hex[:10]}", label=label, source=source, color=color)
            self._tilesets[asset.id] = asset
            return asset

    def list_tilesets(self) -> list[TilesetAsset]:
        with self._lock:
            return list(self._tilesets.values())

    def remove_tileset(self, asset_id: str) -> None:
        with self._lock:
            if asset_id not in self._tilesets:
                raise KeyError(asset_id)
            del self._tilesets[asset_id]

    # ── Models ─────────────────────────────────────────────────────────────

    def add_model(
        self, label: str, url: str, *, lon: float, lat: float,
        height: float = 0.0, heading_deg: float = 0.0, scale: float = 1.0,
    ) -> ModelAsset:
        with self._lock:
            asset = ModelAsset(
                id=f"m_{uuid.uuid4().hex[:10]}", label=label, url=url,
                lon=lon, lat=lat, height=height,
                heading_deg=heading_deg, scale=scale,
            )
            self._models[asset.id] = asset
            return asset

    def list_models(self) -> list[ModelAsset]:
        with self._lock:
            return list(self._models.values())

    def remove_model(self, asset_id: str) -> None:
        with self._lock:
            if asset_id not in self._models:
                raise KeyError(asset_id)
            del self._models[asset_id]

    # ── Combined dump ──────────────────────────────────────────────────────

    def to_json(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tilesets": [asdict(t) for t in self._tilesets.values()],
                "models": [asdict(m) for m in self._models.values()],
            }


# ── Curated 3D asset library ────────────────────────────────────────────────

# A starter list of useful Cesium ion 3D / terrain assets every survey-tech
# user is likely to want. The user supplies their own ion token; these IDs
# resolve under that token. Asset IDs are public.
_ID_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


CURATED_TERRAIN: tuple[dict[str, Any], ...] = (
    {"key": "world_terrain",        "label": "Cesium World Terrain (1m USGS / 10m global)", "ion_id": 1,        "ion": True},
    {"key": "bathymetry",           "label": "Cesium World Bathymetry",                      "ion_id": 2426648, "ion": True},
)

CURATED_TILESETS: tuple[dict[str, Any], ...] = (
    {"key": "osm_buildings",         "label": "Cesium OSM Buildings (global)",     "ion_id": 96188},
    {"key": "google_photorealistic", "label": "Google Photorealistic 3D Tiles",   "ion_id": 2275207},
    {"key": "moon_terrain",          "label": "Moon CAD-grade terrain",            "ion_id": 2684829},
    {"key": "mars_dingo_gap",        "label": "Mars Dingo Gap (Curiosity rover)",  "ion_id": 81097},
)


def curated_catalog() -> dict[str, Any]:
    """Return the curated terrain + tileset catalog for the layers panel."""
    return {"terrain": list(CURATED_TERRAIN), "tilesets": list(CURATED_TILESETS)}


# ── Presentation persistence ────────────────────────────────────────────────


class PresentationStore:
    """JSON-file-backed library of named presentations.

    The default storage directory follows ``platformdirs`` — the same
    convention used by :mod:`meridian.atlas.config` and
    :mod:`meridian.truthchain.keystore`.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else Path(user_data_dir("meridian", appauthor=False)) / "presentations"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        return self._dir

    def list(self) -> list[dict[str, Any]]:
        """Return one summary dict per presentation (no scenes payload)."""
        with self._lock:
            out = []
            for path in sorted(self._dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                out.append({
                    "id": data.get("id"),
                    "title": data.get("title", ""),
                    "description": data.get("description", ""),
                    "scene_count": len(data.get("scenes", [])),
                    "updated_at": data.get("updated_at", ""),
                    "created_at": data.get("created_at", ""),
                })
            return out

    def get(self, presentation_id: str) -> Presentation:
        path = self._path_for(presentation_id)
        if not path.exists():
            raise KeyError(presentation_id)
        return _presentation_from_json(json.loads(path.read_text(encoding="utf-8")))

    def save(self, presentation: Presentation) -> Presentation:
        with self._lock:
            now = _now_iso()
            created_at = presentation.created_at or now
            updated = Presentation(
                id=presentation.id, title=presentation.title,
                description=presentation.description, scenes=presentation.scenes,
                created_at=created_at, updated_at=now, author=presentation.author,
            )
            self._path_for(updated.id).write_text(
                json.dumps(_presentation_to_json(updated), indent=2),
                encoding="utf-8",
            )
            return updated

    def delete(self, presentation_id: str) -> None:
        path = self._path_for(presentation_id)
        if not path.exists():
            raise KeyError(presentation_id)
        path.unlink()

    def _path_for(self, presentation_id: str) -> Path:
        # Defence in depth: refuse anything that isn't already a clean
        # alphanum / dash / underscore id. We *don't* sanitise — silently
        # rewriting the id would make it ambiguous which file holds which
        # presentation. Callers should pass the id we returned from save().
        if not presentation_id or any(c not in _ID_OK for c in presentation_id):
            raise ValueError(f"Invalid presentation_id {presentation_id!r}.")
        return self._dir / f"{presentation_id}.json"


# ── JSON serialisation ──────────────────────────────────────────────────────


def _presentation_to_json(p: Presentation) -> dict[str, Any]:
    return {
        "id": p.id, "title": p.title, "description": p.description,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "author": p.author,
        "scenes": [_scene_to_json(s) for s in p.scenes],
    }


def _scene_to_json(s: Scene) -> dict[str, Any]:
    return {
        "id": s.id, "title": s.title, "narration": s.narration,
        "fly_duration_s": s.fly_duration_s, "auto_advance_s": s.auto_advance_s,
        "clock_iso": s.clock_iso, "selected_parcel_id": s.selected_parcel_id,
        "camera": asdict(s.camera),
        "layers": asdict(s.layers),
        "annotations": [asdict(a) for a in s.annotations],
    }


def _presentation_from_json(d: dict[str, Any]) -> Presentation:
    return Presentation(
        id=d.get("id") or _new_id("p"),
        title=d.get("title", ""),
        description=d.get("description", ""),
        scenes=tuple(_scene_from_json(s) for s in d.get("scenes", [])),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        author=d.get("author", ""),
    )


def _scene_from_json(d: dict[str, Any]) -> Scene:
    cam = d.get("camera") or {}
    layers = d.get("layers") or {}
    annots = d.get("annotations") or []
    return Scene(
        id=d.get("id") or _new_id("s"),
        title=d.get("title", ""),
        narration=d.get("narration", ""),
        camera=CameraState(
            lon=float(cam.get("lon", 0.0)),
            lat=float(cam.get("lat", 0.0)),
            height=float(cam.get("height", 1_000_000.0)),
            heading_deg=float(cam.get("heading_deg", 0.0)),
            pitch_deg=float(cam.get("pitch_deg", -45.0)),
            roll_deg=float(cam.get("roll_deg", 0.0)),
        ),
        layers=LayerState(
            terrain_kind=str(layers.get("terrain_kind", "auto")),
            imagery_visible=tuple(bool(v) for v in layers.get("imagery_visible", [])),
            imagery_alpha=tuple(float(a) for a in layers.get("imagery_alpha", [])),
            tilesets=tuple(str(t) for t in layers.get("tilesets", [])),
            models=tuple(str(m) for m in layers.get("models", [])),
            show_atmosphere=bool(layers.get("show_atmosphere", True)),
            show_sun=bool(layers.get("show_sun", True)),
            show_stars=bool(layers.get("show_stars", True)),
            show_lighting=bool(layers.get("show_lighting", False)),
        ),
        fly_duration_s=float(d.get("fly_duration_s", 2.5)),
        auto_advance_s=(
            float(d["auto_advance_s"]) if d.get("auto_advance_s") is not None else None
        ),
        clock_iso=d.get("clock_iso"),
        selected_parcel_id=d.get("selected_parcel_id"),
        annotations=tuple(
            SceneAnnotation(
                kind=str(a.get("kind", "label")),
                lon=float(a.get("lon", 0.0)),
                lat=float(a.get("lat", 0.0)),
                height=float(a.get("height", 0.0)),
                text=str(a.get("text", "")),
                color=str(a.get("color", "#ffd76e")),
                extra=dict(a.get("extra") or {}),
            ) for a in annots
        ),
    )


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


__all__ = [
    "CURATED_TERRAIN",
    "CURATED_TILESETS",
    "AssetRegistry",
    "CameraState",
    "LayerState",
    "ModelAsset",
    "Presentation",
    "PresentationStore",
    "Scene",
    "SceneAnnotation",
    "TilesetAsset",
    "curated_catalog",
]
