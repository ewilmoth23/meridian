"""Tests for ``meridian.atlas.bookmarks`` and the bookmark REST endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meridian.atlas import create_app
from meridian.atlas.bookmarks import Bookmark, BookmarkStore
from meridian.atlas.presentations import CameraState, LayerState, PresentationStore

# ── Store ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> BookmarkStore:
    return BookmarkStore(path=tmp_path / "bookmarks.json")


def test_store_starts_empty(store):
    assert store.list() == []


def test_create_returns_bookmark_with_id(store):
    cam = CameraState(lon=-97.74, lat=30.27, height=5000.0, pitch_deg=-45.0)
    bm = store.create(title="Test", camera=cam, layers=LayerState(terrain_kind="world_terrain"))
    assert bm.id.startswith("b_")
    assert bm.title == "Test"
    assert bm.camera.lon == -97.74
    assert bm.layers.terrain_kind == "world_terrain"
    assert bm.created_at  # populated


def test_list_returns_newest_first(store):
    cam = CameraState(lon=0, lat=0, height=1000)
    a = store.create(title="A", camera=cam)
    b = store.create(title="B", camera=cam)
    listed = store.list()
    assert listed[0].id == b.id
    assert listed[1].id == a.id


def test_get_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_delete_removes_bookmark(store):
    cam = CameraState(lon=0, lat=0, height=1000)
    bm = store.create(title="X", camera=cam)
    store.delete(bm.id)
    assert store.list() == []
    with pytest.raises(KeyError):
        store.get(bm.id)


def test_delete_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.delete("nope")


def test_update_changes_title(store):
    cam = CameraState(lon=0, lat=0, height=1000)
    bm = store.create(title="Old", camera=cam)
    bm2 = store.update(bm.id, title="New")
    assert bm2.title == "New"
    assert bm2.id == bm.id


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "bm.json"
    s1 = BookmarkStore(path=path)
    s1.create(title="Persistent", camera=CameraState(lon=10, lat=20, height=500))
    s2 = BookmarkStore(path=path)
    assert len(s2.list()) == 1
    assert s2.list()[0].title == "Persistent"


def test_corrupt_file_yields_empty_list(tmp_path):
    path = tmp_path / "bm.json"
    path.write_text("{ not json")
    s = BookmarkStore(path=path)
    assert s.list() == []


def test_store_file_is_chmod_600(tmp_path):
    import os

    path = tmp_path / "bm.json"
    s = BookmarkStore(path=path)
    s.create(title="X", camera=CameraState(lon=0, lat=0, height=1000))
    if os.name != "nt":
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600


# ── REST endpoints ─────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(
        presentation_store=PresentationStore(directory=tmp_path / "p"),
        bookmark_store=BookmarkStore(path=tmp_path / "bm.json"),
    ))


def test_list_initially_empty(client):
    assert client.get("/api/bookmarks").json() == []


def test_create_bookmark_via_endpoint(client):
    r = client.post("/api/bookmarks", json={
        "title": "Mariana Trench",
        "camera": {"lon": 142.0, "lat": 11.5, "height": 50000.0, "pitch_deg": -60.0},
        "layers": {"terrain_kind": "bathymetry"},
        "tags": ["seafloor", "demo"],
    })
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Mariana Trench"
    assert body["camera"]["lon"] == 142.0
    assert body["layers"]["terrain_kind"] == "bathymetry"
    assert body["tags"] == ["seafloor", "demo"]
    assert body["created_at"]


def test_create_then_list_returns_record(client):
    client.post("/api/bookmarks", json={
        "title": "X", "camera": {"lon": 0, "lat": 0, "height": 1000},
    })
    listed = client.get("/api/bookmarks").json()
    assert len(listed) == 1
    assert listed[0]["title"] == "X"


def test_delete_endpoint(client):
    created = client.post("/api/bookmarks", json={
        "title": "Y", "camera": {"lon": 0, "lat": 0, "height": 1000},
    }).json()
    r = client.delete(f"/api/bookmarks/{created['id']}")
    assert r.status_code == 204
    assert client.get("/api/bookmarks").json() == []


def test_delete_unknown_returns_404(client):
    r = client.delete("/api/bookmarks/nope")
    assert r.status_code == 404


def test_create_with_full_layer_state(client):
    r = client.post("/api/bookmarks", json={
        "title": "Full state",
        "camera": {"lon": 1, "lat": 2, "height": 100, "heading_deg": 30, "pitch_deg": -30},
        "layers": {
            "terrain_kind": "ion:1",
            "imagery_visible": [True, False],
            "imagery_alpha": [1.0, 0.4],
            "tilesets": ["t_a", "t_b"],
            "models": ["m_x"],
            "show_lighting": True,
        },
        "clock_iso": "2026-01-01T12:00:00Z",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["layers"]["imagery_alpha"] == [1.0, 0.4]
    assert body["layers"]["tilesets"] == ["t_a", "t_b"]
    assert body["clock_iso"] == "2026-01-01T12:00:00Z"


# ── Frozen dataclass behaviour ──────────────────────────────────────────────


def test_bookmark_record_is_frozen():
    bm = Bookmark(id="b_x", title="t", description="", camera=CameraState(0, 0, 1), layers=LayerState())
    with pytest.raises(AttributeError):
        bm.title = "tampered"  # type: ignore[misc]
