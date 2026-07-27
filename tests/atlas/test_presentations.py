"""Tests for ``meridian.atlas.presentations`` and the 3D / presentation REST endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meridian.atlas import create_app
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

# ── Curated catalog ────────────────────────────────────────────────────────


def test_catalog_has_terrain_and_tilesets():
    cat = curated_catalog()
    assert "terrain" in cat
    assert "tilesets" in cat
    keys = {t["key"] for t in cat["terrain"]}
    assert "world_terrain" in keys
    assert "bathymetry" in keys
    tkeys = {t["key"] for t in cat["tilesets"]}
    assert "osm_buildings" in tkeys
    assert "google_photorealistic" in tkeys


def test_catalog_entries_have_ion_ids():
    for t in curated_catalog()["terrain"]:
        assert isinstance(t["ion_id"], int)
    for t in curated_catalog()["tilesets"]:
        assert isinstance(t["ion_id"], int)


# ── AssetRegistry ──────────────────────────────────────────────────────────


def test_asset_registry_starts_empty():
    r = AssetRegistry()
    assert r.list_tilesets() == []
    assert r.list_models() == []


def test_add_tileset_returns_record():
    r = AssetRegistry()
    a = r.add_tileset("OSM Buildings", "ion:96188")
    assert a.id.startswith("t_")
    assert a.label == "OSM Buildings"
    assert a.source == "ion:96188"
    assert r.list_tilesets() == [a]


def test_add_model_returns_record():
    r = AssetRegistry()
    a = r.add_model("Cesium Air", "https://example/air.glb", lon=-97.74, lat=30.27)
    assert a.id.startswith("m_")
    assert a.url.endswith("air.glb")
    assert a.lon == -97.74 and a.lat == 30.27


def test_remove_tileset_drops_it():
    r = AssetRegistry()
    a = r.add_tileset("X", "ion:1")
    r.remove_tileset(a.id)
    assert r.list_tilesets() == []


def test_remove_unknown_tileset_raises_keyerror():
    r = AssetRegistry()
    with pytest.raises(KeyError):
        r.remove_tileset("nope")


def test_remove_unknown_model_raises_keyerror():
    r = AssetRegistry()
    with pytest.raises(KeyError):
        r.remove_model("nope")


def test_to_json_dumps_both_lists():
    r = AssetRegistry()
    r.add_tileset("X", "ion:1")
    r.add_model("M", "u", lon=0, lat=0)
    out = r.to_json()
    assert len(out["tilesets"]) == 1
    assert len(out["models"]) == 1
    # asdict() round-trip preserves ids etc.
    assert out["tilesets"][0]["source"] == "ion:1"


# ── PresentationStore (file-backed) ────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> PresentationStore:
    return PresentationStore(directory=tmp_path)


def _scene(title: str = "Scene", height: float = 1000.0) -> Scene:
    return Scene(
        id=f"s_{title.replace(' ', '_').lower()}",
        title=title,
        narration=f"Narration for {title}",
        camera=CameraState(lon=-97.74, lat=30.27, height=height),
        layers=LayerState(terrain_kind="world_terrain"),
        fly_duration_s=2.0,
        annotations=(
            SceneAnnotation(kind="label", lon=-97.74, lat=30.27, text="here"),
        ),
    )


def test_store_save_and_get_roundtrip(store):
    p = Presentation(id="p_alpha", title="Alpha", scenes=(_scene("One"), _scene("Two")))
    saved = store.save(p)
    assert saved.created_at  # populated
    assert saved.updated_at
    again = store.get("p_alpha")
    assert again.title == "Alpha"
    assert len(again.scenes) == 2
    assert again.scenes[0].title == "One"
    assert again.scenes[0].layers.terrain_kind == "world_terrain"
    assert again.scenes[0].annotations[0].text == "here"


def test_store_list_summarises_each(store):
    store.save(Presentation(id="p_a", title="A", scenes=(_scene(),)))
    store.save(Presentation(id="p_b", title="B", scenes=(_scene("S1"), _scene("S2"))))
    listed = store.list()
    by_id = {s["id"]: s for s in listed}
    assert by_id["p_a"]["scene_count"] == 1
    assert by_id["p_b"]["scene_count"] == 2
    assert by_id["p_b"]["title"] == "B"


def test_store_get_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_store_delete_removes_file(store):
    p = store.save(Presentation(id="p_x", title="X", scenes=()))
    store.delete("p_x")
    assert store.list() == []
    assert not (store.directory / "p_x.json").exists()
    with pytest.raises(KeyError):
        store.get("p_x")


def test_store_delete_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.delete("does-not-exist")


def test_store_save_preserves_created_at(store):
    p1 = store.save(Presentation(id="p_q", title="Q", scenes=()))
    first_created = p1.created_at
    # Save again with a new title; created_at should not move.
    p2 = store.save(Presentation(id="p_q", title="Q-edited", scenes=()))
    assert p2.created_at == first_created


def test_store_rejects_unsafe_id(store):
    with pytest.raises(ValueError):
        store.save(Presentation(id="../../../etc/passwd", title="evil", scenes=()))


def test_store_skips_corrupt_files(store, tmp_path):
    (store.directory / "broken.json").write_text("{ not json")
    listed = store.list()
    assert listed == []


def test_store_saved_file_is_well_formed_json(store):
    store.save(Presentation(id="p_w", title="W", scenes=(_scene(),)))
    text = (store.directory / "p_w.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["title"] == "W"
    assert isinstance(data["scenes"], list)


# ── REST endpoints ─────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(presentation_store=PresentationStore(directory=tmp_path)))


def test_catalog_endpoint(client):
    r = client.get("/api/assets/catalog")
    assert r.status_code == 200
    body = r.json()
    assert "world_terrain" in {t["key"] for t in body["terrain"]}


def test_add_and_remove_tileset_endpoint(client):
    r = client.post("/api/assets/tilesets", json={"label": "Buildings", "source": "ion:96188"})
    assert r.status_code == 201
    aid = r.json()["id"]
    r2 = client.get("/api/assets")
    assert any(t["id"] == aid for t in r2.json()["tilesets"])
    r3 = client.delete(f"/api/assets/tilesets/{aid}")
    assert r3.status_code == 204
    r4 = client.delete(f"/api/assets/tilesets/{aid}")
    assert r4.status_code == 404


def test_add_and_remove_model_endpoint(client):
    r = client.post("/api/assets/models", json={
        "label": "Plane", "url": "https://example/p.glb",
        "lon": -97.74, "lat": 30.27, "height": 50,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["lon"] == -97.74
    aid = body["id"]
    assert client.delete(f"/api/assets/models/{aid}").status_code == 204
    assert client.delete(f"/api/assets/models/{aid}").status_code == 404


def test_list_presentations_initially_empty(client):
    assert client.get("/api/presentations").json() == []


def test_create_presentation_returns_full_record(client):
    r = client.post("/api/presentations", json={
        "title": "Tour",
        "scenes": [
            {"title": "Wide", "camera": {"lon": -97.7, "lat": 30.3, "height": 5000}},
            {"title": "Close", "camera": {"lon": -97.74, "lat": 30.27, "height": 500}},
        ],
    })
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Tour"
    assert len(body["scenes"]) == 2
    assert body["scenes"][0]["camera"]["lon"] == -97.7
    assert body["created_at"]
    assert body["updated_at"]


def test_get_presentation_roundtrip(client):
    created = client.post("/api/presentations", json={
        "title": "X", "scenes": [{"title": "A", "camera": {"lon": 0, "lat": 0, "height": 1000}}],
    }).json()
    again = client.get(f"/api/presentations/{created['id']}").json()
    assert again["id"] == created["id"]
    assert again["scenes"][0]["title"] == "A"


def test_get_unknown_returns_404(client):
    assert client.get("/api/presentations/nope").status_code == 404


def test_update_presentation(client):
    created = client.post("/api/presentations", json={
        "title": "Draft", "scenes": [{"title": "S", "camera": {"lon": 0, "lat": 0, "height": 100}}],
    }).json()
    r = client.put(f"/api/presentations/{created['id']}", json={
        "title": "Final", "scenes": [
            {"title": "S1", "camera": {"lon": 1, "lat": 1, "height": 200}},
            {"title": "S2", "camera": {"lon": 2, "lat": 2, "height": 300}},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Final"
    assert len(body["scenes"]) == 2
    assert body["scenes"][1]["camera"]["lon"] == 2
    # created_at preserved.
    assert body["created_at"] == created["created_at"]


def test_update_unknown_returns_404(client):
    r = client.put("/api/presentations/nope", json={"title": "X", "scenes": []})
    assert r.status_code == 404


def test_delete_presentation(client):
    created = client.post("/api/presentations", json={"title": "Y", "scenes": []}).json()
    assert client.delete(f"/api/presentations/{created['id']}").status_code == 204
    assert client.get(f"/api/presentations/{created['id']}").status_code == 404


def test_delete_unknown_returns_404(client):
    assert client.delete("/api/presentations/nope").status_code == 404


def test_full_round_trip_with_layer_state(client):
    payload = {
        "title": "Bathymetry tour",
        "description": "From space to seafloor",
        "scenes": [
            {
                "title": "Earth", "narration": "Starting at the global view",
                "camera": {"lon": -95, "lat": 35, "height": 16_000_000, "pitch_deg": -90},
                "layers": {
                    "terrain_kind": "bathymetry",
                    "imagery_visible": [True, False],
                    "imagery_alpha": [1.0, 0.5],
                    "tilesets": ["t_xyz"],
                    "models": [],
                    "show_lighting": True,
                },
                "fly_duration_s": 4.5,
                "auto_advance_s": 5.0,
                "clock_iso": "2026-06-21T18:00:00Z",
                "annotations": [{"kind": "label", "lon": -95, "lat": 35, "text": "Globe"}],
            },
        ],
    }
    created = client.post("/api/presentations", json=payload).json()
    again = client.get(f"/api/presentations/{created['id']}").json()
    s = again["scenes"][0]
    assert s["layers"]["terrain_kind"] == "bathymetry"
    assert s["layers"]["imagery_alpha"] == [1.0, 0.5]
    assert s["layers"]["tilesets"] == ["t_xyz"]
    assert s["clock_iso"] == "2026-06-21T18:00:00Z"
    assert s["annotations"][0]["text"] == "Globe"
    assert s["auto_advance_s"] == 5.0


def test_atlas_page_has_3d_chrome(client):
    body = client.get("/atlas/").text
    for must in ("3D Terrain", "presStrip", "timeBar", "dropOverlay", "place_model", "data-tool=\"profile\""):
        assert must in body, f"missing {must!r} in rendered atlas page"
