"""Tests for ``meridian.atlas.edit_session`` and the interactive REST endpoints."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from meridian.atlas import create_app
from meridian.atlas.edit_session import (
    EditSession,
    haversine_m,
    initial_bearing_deg,
    measure_segments,
)

# A 100-m square in Travis Heights, Austin TX (chosen because the demo parcel
# in tile_service.py also sits in the same neighbourhood).
SQ = [
    [-97.7444, 30.2672],
    [-97.7434, 30.2672],
    [-97.7434, 30.2682],
    [-97.7444, 30.2682],
]


# ── EditSession ─────────────────────────────────────────────────────────────


def test_create_returns_full_feature_with_metrics():
    s = EditSession()
    f = s.create_parcel(SQ, {"name": "Test", "color": "#ff0000"})
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Polygon"
    p = f["properties"]
    assert p["name"] == "Test"
    assert p["color"] == "#ff0000"
    # Geodesic area should be roughly 96 m × 111 m ≈ 10_700 m² at lat 30°.
    assert 10_000 < p["area_m2"] < 13_000
    assert 380 < p["perimeter_m"] < 460


def test_create_closed_or_open_ring_both_ok():
    s = EditSession()
    open_ring = s.create_parcel(SQ, None)
    closed_ring = s.create_parcel([*SQ, SQ[0]], None)
    # Vertex count is reported as the number of distinct corners in both cases.
    assert open_ring["properties"]["vertex_count"] == 4
    assert closed_ring["properties"]["vertex_count"] == 4


def test_list_parcels_returns_each_created():
    s = EditSession()
    s.create_parcel(SQ, {"name": "A"})
    s.create_parcel([[-97.7424, 30.2672], [-97.7414, 30.2672], [-97.7414, 30.2682], [-97.7424, 30.2682]], {"name": "B"})
    listed = s.list_parcels()
    assert len(listed) == 2
    assert {f["properties"]["name"] for f in listed} == {"A", "B"}


def test_get_returns_single_parcel():
    s = EditSession()
    f = s.create_parcel(SQ, {"name": "X"})
    again = s.get_parcel(f["id"])
    assert again["id"] == f["id"]


def test_update_geometry_changes_area_and_keeps_metadata():
    s = EditSession()
    f = s.create_parcel(SQ, {"name": "Movable", "color": "#00ff00"})
    bigger = [
        [-97.7454, 30.2662],
        [-97.7424, 30.2662],
        [-97.7424, 30.2692],
        [-97.7454, 30.2692],
    ]
    f2 = s.update_parcel_geometry(f["id"], bigger)
    assert f2["id"] == f["id"]
    assert f2["properties"]["name"] == "Movable"
    assert f2["properties"]["color"] == "#00ff00"
    assert f2["properties"]["area_m2"] > f["properties"]["area_m2"] * 5


def test_update_properties_merges_extras():
    s = EditSession()
    f = s.create_parcel(SQ, {"name": "x", "extra": {"k1": "v1"}})
    f2 = s.update_parcel_properties(f["id"], {"owner": "Acme", "extra": {"k2": "v2"}})
    assert f2["properties"]["owner"] == "Acme"
    assert f2["properties"]["name"] == "x"  # preserved
    assert f2["properties"]["extra"] == {"k1": "v1", "k2": "v2"}


def test_update_unknown_id_raises_keyerror():
    s = EditSession()
    with pytest.raises(KeyError):
        s.update_parcel_geometry("nope", SQ)


def test_delete_parcel_removes_it():
    s = EditSession()
    f = s.create_parcel(SQ, None)
    s.delete_parcel(f["id"])
    assert s.list_parcels() == []
    with pytest.raises(KeyError):
        s.get_parcel(f["id"])


def test_split_parcel_yields_two_with_combined_area():
    s = EditSession()
    f = s.create_parcel(SQ, {"name": "Tract"})
    cut_lon = (SQ[0][0] + SQ[1][0]) / 2  # vertical cut down the middle
    left, right = s.split_parcel(
        f["id"],
        cut=([cut_lon, SQ[0][1] - 0.0005], [cut_lon, SQ[2][1] + 0.0005]),
        left_name="Left", right_name="Right",
    )
    total = left["properties"]["area_m2"] + right["properties"]["area_m2"]
    assert math.isclose(total, f["properties"]["area_m2"], rel_tol=0.01)
    assert left["properties"]["name"] == "Left"
    assert right["properties"]["name"] == "Right"


def test_clear_drops_everything():
    s = EditSession()
    s.create_parcel(SQ, None)
    s.create_parcel([[-97.74, 30.26], [-97.73, 30.26], [-97.73, 30.27], [-97.74, 30.27]], None)
    s.clear()
    assert s.list_parcels() == []


def test_snap_finds_nearby_corner():
    s = EditSession()
    s.create_parcel(SQ, None)
    # 3 metres away from a corner at lat 30° ≈ 2.7e-5 deg.
    hit = s.snap_lonlat(SQ[0][0] + 1e-5, SQ[0][1], tolerance_m=5.0)
    assert hit is not None
    assert hit["distance_m"] < 5.0


def test_snap_returns_none_outside_tolerance():
    s = EditSession()
    s.create_parcel(SQ, None)
    miss = s.snap_lonlat(SQ[0][0] + 0.01, SQ[0][1], tolerance_m=5.0)
    assert miss is None


def test_to_geojson_is_well_formed_feature_collection():
    s = EditSession()
    s.create_parcel(SQ, {"name": "X"})
    fc = s.to_geojson()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    assert fc["features"][0]["geometry"]["type"] == "Polygon"


# ── geodesic helpers ────────────────────────────────────────────────────────


def test_haversine_zero_distance_is_zero():
    assert haversine_m(30, -97, 30, -97) == pytest.approx(0.0)


def test_haversine_one_degree_north_is_about_111km():
    d = haversine_m(30, -97, 31, -97)
    assert 110_000 < d < 112_000


def test_initial_bearing_due_east():
    b = initial_bearing_deg(30, -97, 30, -96)
    # At 30°N, due east stays close to 90° but is slightly less because of
    # great-circle convergence; allow a wide gate.
    assert 89.5 < b < 90.5


def test_initial_bearing_due_north_is_zero():
    b = initial_bearing_deg(30, -97, 31, -97)
    assert abs(b) < 0.01 or abs(b - 360) < 0.01


def test_measure_segments_aggregates_total_and_closure():
    out = measure_segments(SQ)
    assert len(out["segments"]) == 3  # n-1 segments between 4 points
    assert out["total_m"] > 0
    assert out["closure_distance_m"] is not None  # last → first
    assert out["area_m2"] > 0


def test_measure_two_points_has_no_closure():
    out = measure_segments([SQ[0], SQ[1]])
    assert out["closure_distance_m"] is None
    assert out["area_m2"] == 0


# ── REST endpoints ─────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["service"] == "meridian.atlas"


def test_create_parcel_endpoint(client):
    r = client.post(
        "/api/session/parcels",
        json={"ring": SQ, "properties": {"name": "API-test"}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["properties"]["name"] == "API-test"
    assert "area_m2" in body["properties"]


def test_list_session_parcels(client):
    client.post("/api/session/parcels", json={"ring": SQ, "properties": {"name": "A"}})
    fc = client.get("/api/session/parcels.geojson").json()
    assert fc["type"] == "FeatureCollection"
    assert any(f["properties"]["name"] == "A" for f in fc["features"])


def test_update_geometry_endpoint(client):
    created = client.post("/api/session/parcels", json={"ring": SQ, "properties": {}}).json()
    bigger = [
        [-97.7454, 30.2662], [-97.7424, 30.2662],
        [-97.7424, 30.2692], [-97.7454, 30.2692],
    ]
    r = client.put(f"/api/session/parcels/{created['id']}/geometry", json={"ring": bigger})
    assert r.status_code == 200
    assert r.json()["properties"]["area_m2"] > created["properties"]["area_m2"] * 5


def test_update_properties_endpoint(client):
    created = client.post("/api/session/parcels", json={"ring": SQ, "properties": {}}).json()
    r = client.put(f"/api/session/parcels/{created['id']}/properties",
                   json={"properties": {"owner": "Acme"}})
    assert r.status_code == 200
    assert r.json()["properties"]["owner"] == "Acme"


def test_update_unknown_returns_404(client):
    r = client.put("/api/session/parcels/nope/geometry", json={"ring": SQ})
    assert r.status_code == 404


def test_delete_endpoint(client):
    created = client.post("/api/session/parcels", json={"ring": SQ, "properties": {}}).json()
    r = client.delete(f"/api/session/parcels/{created['id']}")
    assert r.status_code == 204
    fc = client.get("/api/session/parcels.geojson").json()
    assert all(f["id"] != created["id"] for f in fc["features"])


def test_delete_unknown_returns_404(client):
    r = client.delete("/api/session/parcels/nope")
    assert r.status_code == 404


def test_split_endpoint(client):
    created = client.post("/api/session/parcels", json={"ring": SQ, "properties": {"name": "T"}}).json()
    cut_lon = (SQ[0][0] + SQ[1][0]) / 2
    r = client.post(
        f"/api/session/parcels/{created['id']}/split",
        json={"cut_from": [cut_lon, SQ[0][1] - 0.001], "cut_to": [cut_lon, SQ[2][1] + 0.001]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "left" in body and "right" in body
    assert body["left"]["properties"]["area_m2"] > 0
    assert body["right"]["properties"]["area_m2"] > 0


def test_split_unknown_returns_404(client):
    r = client.post("/api/session/parcels/nope/split",
                    json={"cut_from": [-97.74, 30.26], "cut_to": [-97.74, 30.27]})
    assert r.status_code == 404


def test_measure_endpoint(client):
    r = client.post("/api/session/measure", json={"positions": SQ})
    assert r.status_code == 200
    assert r.json()["total_m"] > 0
    assert r.json()["closure_distance_m"] is not None


def test_measure_too_few_points_400(client):
    r = client.post("/api/session/measure", json={"positions": [SQ[0]]})
    assert r.status_code == 400


def test_snap_hit(client):
    client.post("/api/session/parcels", json={"ring": SQ, "properties": {}})
    r = client.get("/api/session/snap", params={"lon": SQ[0][0] + 1e-5, "lat": SQ[0][1], "tolerance_m": 5})
    body = r.json()
    assert body["hit"] is True
    assert body["node"]["distance_m"] < 5.0


def test_snap_miss(client):
    client.post("/api/session/parcels", json={"ring": SQ, "properties": {}})
    r = client.get("/api/session/snap", params={"lon": -97.0, "lat": 30.0, "tolerance_m": 1})
    assert r.json()["hit"] is False


def test_clear_endpoint(client):
    client.post("/api/session/parcels", json={"ring": SQ, "properties": {}})
    r = client.delete("/api/session/clear")
    assert r.status_code == 204
    fc = client.get("/api/session/parcels.geojson").json()
    assert fc["features"] == []


def test_atlas_page_has_new_ui_chrome(client):
    r = client.get("/atlas/")
    assert r.status_code == 200
    body = r.text
    # Spot-check several distinctive elements of the rewrite.
    assert "MERIDIAN" in body
    assert 'id="cesiumContainer"' in body
    assert 'id="toolPalette"' in body
    assert 'id="hudLonLat"' in body
    assert "ScreenSpaceEventHandler" in body  # confirms the script is embedded
