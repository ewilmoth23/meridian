"""Python-side controller for the embedded Cesium viewer.

Talks to the in-process JavaScript runtime via :class:`QWebChannel` and
provides a small, typed Python API: load parcels, fly to a point, push
edits, listen to user clicks. The widget itself is a
:class:`QWebEngineView` configured to load the Atlas tile service URL
(``http://127.0.0.1:<port>/atlas/`` by default).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass(frozen=True, slots=True)
class AtlasServerHandle:
    """Handle returned by :func:`launch_tile_service`."""

    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def viewer_url(self) -> str:
        return f"{self.url}/atlas/"


def launch_tile_service(
    app: FastAPI,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    daemon: bool = True,
) -> AtlasServerHandle:
    """Launch a uvicorn-hosted FastAPI app on a background thread.

    Returns the URL/port the desktop GUI should point its
    :class:`QWebEngineView` at.
    """
    try:
        import uvicorn
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Atlas requires uvicorn. Install with: pip install uvicorn[standard]"
        ) from e
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)

    def _run() -> None:
        server.run()

    thread = threading.Thread(target=_run, daemon=daemon, name="meridian-atlas")
    thread.start()
    # Wait briefly for the server to bind. uvicorn doesn't expose a
    # ready-event, so we poll the started flag.
    import time as _t
    deadline = _t.time() + 5.0
    while not server.started and _t.time() < deadline:
        _t.sleep(0.05)
    if not server.started:
        raise RuntimeError("Atlas tile service failed to start within 5 seconds.")
    return AtlasServerHandle(host=host, port=port)


def make_widget(handle: AtlasServerHandle) -> object:
    """Return a :class:`QWebEngineView` pointing at the tile service.

    Imported lazily — this is the only place where the desktop
    dependency is required, so headless tests / CI can import the rest
    of :mod:`meridian.atlas` without PySide6.
    """
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Atlas widget requires PySide6 + QtWebEngine. "
            "Install with: pip install 'meridian[desktop]'"
        ) from e
    view = QWebEngineView()
    view.load(QUrl(handle.viewer_url))
    return view
