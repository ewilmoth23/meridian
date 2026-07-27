"""Persistent atlas configuration — Cesium Ion token, Google Maps key, etc.

Stored in a per-user config file (``platformdirs.user_config_dir("meridian")``)
so the token survives across CLI invocations and is *not* committed to the
repository.

Resolution order for any value:

1. Explicit argument passed by the caller (CLI flag, function param)
2. Environment variable (``MERIDIAN_ION_TOKEN`` / ``MERIDIAN_GOOGLE_MAPS_KEY``)
3. Persisted config file
4. ``None`` (fall back to public providers — see ``static/index.html``)
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

CONFIG_FILENAME = "atlas.json"
ION_TOKEN_ENV = "MERIDIAN_ION_TOKEN"
GOOGLE_MAPS_KEY_ENV = "MERIDIAN_GOOGLE_MAPS_KEY"


@dataclass(frozen=True, slots=True)
class AtlasConfig:
    ion_token: str | None = None
    google_maps_key: str | None = None


def _config_path() -> Path:
    return Path(user_config_dir("meridian", appauthor=False)) / CONFIG_FILENAME


def load_atlas_config() -> AtlasConfig:
    """Read the on-disk config, returning an empty config if none exists."""
    path = _config_path()
    if not path.exists():
        return AtlasConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AtlasConfig()
    return AtlasConfig(
        ion_token=_clean(data.get("ion_token")),
        google_maps_key=_clean(data.get("google_maps_key")),
    )


def save_atlas_config(cfg: AtlasConfig) -> Path:
    """Persist the config and return the file path written."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ion_token": cfg.ion_token,
        "google_maps_key": cfg.google_maps_key,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return path


def resolve_ion_token(cli_value: str | None = None) -> str | None:
    """Resolve the Ion token using the documented precedence chain."""
    return _clean(cli_value) or _clean(os.environ.get(ION_TOKEN_ENV)) or load_atlas_config().ion_token


def resolve_google_maps_key(cli_value: str | None = None) -> str | None:
    return (
        _clean(cli_value)
        or _clean(os.environ.get(GOOGLE_MAPS_KEY_ENV))
        or load_atlas_config().google_maps_key
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
