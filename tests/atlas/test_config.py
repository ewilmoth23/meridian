"""Tests for ``meridian.atlas.config``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meridian.atlas import config as atlas_config
from meridian.atlas.config import (
    ION_TOKEN_ENV,
    AtlasConfig,
    load_atlas_config,
    resolve_google_maps_key,
    resolve_ion_token,
    save_atlas_config,
)


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    """Redirect the config file to a tmp path and clear env for each test."""
    monkeypatch.setattr(atlas_config, "_config_path", lambda: tmp_path / "atlas.json")
    monkeypatch.delenv(ION_TOKEN_ENV, raising=False)
    monkeypatch.delenv("MERIDIAN_GOOGLE_MAPS_KEY", raising=False)
    yield


def test_load_returns_empty_when_missing():
    cfg = load_atlas_config()
    assert cfg.ion_token is None
    assert cfg.google_maps_key is None


def test_save_and_reload_roundtrip():
    written = save_atlas_config(AtlasConfig(ion_token="abc", google_maps_key="xyz"))
    assert Path(written).exists()
    loaded = load_atlas_config()
    assert loaded.ion_token == "abc"
    assert loaded.google_maps_key == "xyz"


def test_save_sets_restrictive_permissions():
    written = save_atlas_config(AtlasConfig(ion_token="abc"))
    if os.name != "nt":
        mode = written.stat().st_mode & 0o777
        assert mode == 0o600


def test_load_recovers_from_corrupt_json(tmp_path):
    path = atlas_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    cfg = load_atlas_config()
    assert cfg.ion_token is None


def test_resolve_precedence_cli_wins(monkeypatch):
    monkeypatch.setenv(ION_TOKEN_ENV, "from-env")
    save_atlas_config(AtlasConfig(ion_token="from-config"))
    assert resolve_ion_token("from-cli") == "from-cli"


def test_resolve_precedence_env_beats_config(monkeypatch):
    monkeypatch.setenv(ION_TOKEN_ENV, "from-env")
    save_atlas_config(AtlasConfig(ion_token="from-config"))
    assert resolve_ion_token() == "from-env"


def test_resolve_falls_back_to_config():
    save_atlas_config(AtlasConfig(ion_token="from-config"))
    assert resolve_ion_token() == "from-config"


def test_resolve_returns_none_when_unset():
    assert resolve_ion_token() is None


def test_resolve_treats_blank_as_unset(monkeypatch):
    save_atlas_config(AtlasConfig(ion_token="from-config"))
    assert resolve_ion_token("   ") == "from-config"


def test_resolve_google_maps_key_uses_same_chain(monkeypatch):
    monkeypatch.setenv("MERIDIAN_GOOGLE_MAPS_KEY", "env-key")
    save_atlas_config(AtlasConfig(google_maps_key="cfg-key"))
    assert resolve_google_maps_key() == "env-key"
    assert resolve_google_maps_key("cli-key") == "cli-key"
