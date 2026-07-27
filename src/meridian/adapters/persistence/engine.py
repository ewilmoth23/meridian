"""SQLAlchemy engine factory.

Two backends supported:

* **SQLite + SpatiaLite** — default for desktop and tests. Single file,
  no server required. Spatial extension loaded at session connect time
  via the ``connect`` event hook.
* **PostgreSQL + PostGIS** — for multi-user deployments. Pass any
  ``postgresql://`` URL to :func:`create_engine_for`.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

#: SpatiaLite library candidates we'll try to load (best-effort).
_SPATIALITE_CANDIDATES: tuple[str, ...] = (
    "mod_spatialite",
    "/opt/homebrew/lib/mod_spatialite.dylib",     # macOS Homebrew
    "/usr/local/lib/mod_spatialite.dylib",
    "/usr/lib/x86_64-linux-gnu/mod_spatialite.so",  # Ubuntu/Debian
    "C:/SpatiaLite/mod_spatialite.dll",
)


def create_engine_for(url: str | Path, *, echo: bool = False, spatialite: bool = True) -> Engine:
    """Create a SQLAlchemy engine.

    ``url`` may be a SQLAlchemy URL string or a path. A path is treated
    as a SQLite DB file.
    """
    if isinstance(url, Path) or (isinstance(url, str) and not url.startswith(("sqlite", "postgres"))):
        url_str = f"sqlite:///{Path(url).resolve()}"
    else:
        url_str = str(url)

    is_sqlite = url_str.startswith("sqlite")
    engine = create_engine(
        url_str,
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )
    if is_sqlite and spatialite:
        enable_spatialite(engine)
    return engine


def enable_spatialite(engine: Engine) -> None:
    """Wire a connect-event hook to load mod_spatialite.

    SpatiaLite is best-effort: if loading fails we log a warning and
    proceed without it. Spatial queries will then fail at use time.
    """
    @event.listens_for(engine, "connect")
    def _load_extension(dbapi_conn, _record) -> None:
        try:
            dbapi_conn.enable_load_extension(True)
        except AttributeError:
            return
        loaded = False
        for candidate in _SPATIALITE_CANDIDATES:
            try:
                dbapi_conn.load_extension(candidate)
                loaded = True
                logger.debug("Loaded SpatiaLite from %s", candidate)
                break
            except Exception:
                continue
        if not loaded:
            logger.warning(
                "Could not load SpatiaLite extension. Spatial queries will not work. "
                "Install via 'brew install libspatialite' (macOS) or "
                "'apt-get install libspatialite-dev' (Linux)."
            )
        with contextlib.suppress(AttributeError):
            dbapi_conn.enable_load_extension(False)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
