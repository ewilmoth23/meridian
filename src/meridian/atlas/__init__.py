"""Atlas — the integrated 3D globe (v0.5).

Live, two-way 3D globe over the canonical Survey model. Reads from
:mod:`meridian.domain.survey`, streams 3D Tiles 1.1 / GeoJSON / COPC via
a local FastAPI tile service, and embeds CesiumJS in the desktop app
through QtWebEngine + QWebChannel.

Status: spike landed. The tile service and the Cesium HTML viewer ship
in this package; the QtWebEngine widget hosts them in the desktop app.

Components:

* ``tile_service.py`` — FastAPI app exposing:
    - ``/tiles/parcel/{id}.json``           (3D Tiles tileset for a parcel)
    - ``/tiles/cloud/{id}.copc.laz``        (range-request streaming of LAZ)
    - ``/tiles/contours/{id}.geojson``      (contour features)
    - ``/imagery/{provider}/{z}/{x}/{y}``   (proxy with Cesium ion / Bing key handling)
* ``cesium_client.py`` — Python-side controller that talks to the embedded
  CesiumJS via QWebChannel: load tilesets, fly to parcels, push edits.
* ``three_d_tiles.py`` — adapter that converts a :class:`Survey` to a
  3D Tiles tileset on the fly (B3DM for parcels, PNTS for points).
* ``ion_credentials.py`` — manages the user's Cesium ion key, Google Maps
  Platform key, and any other tile-provider credentials. Keys are stored
  via :mod:`platformdirs` and never embedded in the binary.

Stack picks (validated 2026):

* CesiumJS (Apache 2.0) bundled locally, ~30 MB.
* QtWebEngine + QWebChannel — canonical Qt-embed pattern in 2026.
* 3D Tiles 1.1 (OGC Community Standard); 2.0 in draft late 2025.
* COPC for single-site LiDAR; 3D Tiles 1.1 for regional point clouds.
* USGS 3DEP terrain (1 m CONUS coverage ~80%+); free via AWS Open Data.
* Cesium ion key as optional upgrade (Cesium World Terrain + Bing/Maxar).
* Google Photorealistic 3D Tiles as optional layer (user supplies key;
  ToS forbid offline caching — surface that in the UI).
"""

from __future__ import annotations

from meridian.atlas.cesium_client import (
    AtlasServerHandle,
    launch_tile_service,
    make_widget,
)
from meridian.atlas.tile_service import create_app

__all__ = ["AtlasServerHandle", "create_app", "launch_tile_service", "make_widget"]
