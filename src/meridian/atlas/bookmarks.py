"""Named-camera-position bookmarks for the Atlas viewer.

A bookmark is a one-off named camera + clock state — the same shape as a
single :class:`~meridian.atlas.presentations.Scene` but standalone, so the
user can quick-jump to favourite locations without building a presentation.

Persisted as a single JSON file in ``platformdirs.user_data_dir("meridian")``
because the data is small (a few dozen records) and a sqlite roundtrip
isn't worth the indirection.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from meridian.atlas.presentations import CameraState, LayerState


@dataclass(frozen=True, slots=True)
class Bookmark:
    id: str
    title: str
    description: str
    camera: CameraState
    layers: LayerState
    clock_iso: str | None = None
    created_at: str = ""
    tags: tuple[str, ...] = ()


class BookmarkStore:
    """In-memory cache + on-disk file for the user's bookmarks."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else Path(user_data_dir("meridian", appauthor=False)) / "bookmarks.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items: dict[str, Bookmark] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for d in data.get("bookmarks", []):
            try:
                bm = _bookmark_from_json(d)
            except Exception:
                continue
            self._items[bm.id] = bm

    def _save(self) -> None:
        with self._lock:
            payload = {"bookmarks": [_bookmark_to_json(b) for b in self._items.values()]}
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            with contextlib.suppress(OSError):
                self._path.chmod(0o600)

    # ── CRUD ───────────────────────────────────────────────────────────────

    def list(self) -> list[Bookmark]:
        with self._lock:
            return sorted(self._items.values(), key=lambda b: b.created_at, reverse=True)

    def get(self, bookmark_id: str) -> Bookmark:
        with self._lock:
            if bookmark_id not in self._items:
                raise KeyError(bookmark_id)
            return self._items[bookmark_id]

    def create(
        self,
        *,
        title: str,
        camera: CameraState,
        layers: LayerState | None = None,
        description: str = "",
        clock_iso: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Bookmark:
        with self._lock:
            bm = Bookmark(
                id=f"b_{uuid.uuid4().hex[:10]}",
                title=title,
                description=description,
                camera=camera,
                layers=layers or LayerState(),
                clock_iso=clock_iso,
                created_at=_now_iso(),
                tags=tags,
            )
            self._items[bm.id] = bm
            self._save()
            return bm

    def update(self, bookmark_id: str, **changes: Any) -> Bookmark:
        with self._lock:
            existing = self.get(bookmark_id)
            updated = Bookmark(
                id=existing.id,
                title=changes.get("title", existing.title),
                description=changes.get("description", existing.description),
                camera=changes.get("camera", existing.camera),
                layers=changes.get("layers", existing.layers),
                clock_iso=changes.get("clock_iso", existing.clock_iso),
                created_at=existing.created_at,
                tags=tuple(changes.get("tags", existing.tags)),
            )
            self._items[bookmark_id] = updated
            self._save()
            return updated

    def delete(self, bookmark_id: str) -> None:
        with self._lock:
            if bookmark_id not in self._items:
                raise KeyError(bookmark_id)
            del self._items[bookmark_id]
            self._save()


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bookmark_to_json(b: Bookmark) -> dict[str, Any]:
    return {
        "id": b.id, "title": b.title, "description": b.description,
        "clock_iso": b.clock_iso, "created_at": b.created_at,
        "tags": list(b.tags),
        "camera": asdict(b.camera),
        "layers": asdict(b.layers),
    }


def _bookmark_from_json(d: dict[str, Any]) -> Bookmark:
    cam = d.get("camera") or {}
    layers = d.get("layers") or {}
    return Bookmark(
        id=str(d["id"]),
        title=str(d.get("title", "")),
        description=str(d.get("description", "")),
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
        clock_iso=d.get("clock_iso"),
        created_at=str(d.get("created_at", "")),
        tags=tuple(str(t) for t in d.get("tags", [])),
    )


__all__ = ["Bookmark", "BookmarkStore"]
