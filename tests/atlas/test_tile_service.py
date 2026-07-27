"""Tile service smoke tests (FastAPI TestClient — no live server)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(**kwargs):
    from meridian.atlas.tile_service import create_app
    return TestClient(create_app(**kwargs))


def test_health_demo_mode():
    with _client() as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["demo_mode"] is True
    assert body["ion_configured"] is False


def test_health_with_ion_token():
    with _client(cesium_ion_token="abc123") as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ion_configured"] is True


def test_demo_parcels_geojson():
    with _client() as c:
        r = c.get("/api/parcels.geojson")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    geom = fc["features"][0]["geometry"]
    assert geom["type"] == "Polygon"
    # Demo parcel sits in Austin, TX.
    assert -98.0 < geom["coordinates"][0][0][0] < -97.0


def test_atlas_html_served():
    with _client() as c:
        r = c.get("/atlas/")
    assert r.status_code == 200
    assert "Meridian Atlas" in r.text
    assert "cesiumContainer" in r.text


def test_projects_demo_mode():
    with _client() as c:
        r = c.get("/api/projects")
    body = r.json()
    assert body == [{"id": "demo", "name": "Demo (no project DB attached)"}]
