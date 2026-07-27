"""Layer-config preset tests."""

from __future__ import annotations

import pytest

from meridian.adapters.cad.layer_config import (
    ALTA_NSPS_PRESET,
    CIVIL3D_PRESET,
    DEFAULT_PRESET,
    MINIMAL_PRESET,
    NCS_PRESET,
    PRESETS,
    SemanticLayer,
    get_preset,
)


def test_default_preset_resolves_every_semantic_layer():
    for sem in SemanticLayer:
        style = DEFAULT_PRESET.resolve(sem)
        assert style.name


def test_alta_uses_v_prefix():
    assert ALTA_NSPS_PRESET.resolve(SemanticLayer.BOUNDARY).name.startswith("V-")


def test_civil3d_uses_c_prefix():
    assert CIVIL3D_PRESET.resolve(SemanticLayer.BOUNDARY).name.startswith("C-")


def test_minimal_collapses_to_few_layers():
    names = set(MINIMAL_PRESET.names)
    assert len(names) < 18  # default has 18 distinct semantic slots


def test_get_preset_round_trip():
    assert get_preset("default") is DEFAULT_PRESET
    assert get_preset("alta_nsps") is ALTA_NSPS_PRESET
    assert get_preset("civil3d") is CIVIL3D_PRESET
    assert get_preset("ncs") is NCS_PRESET


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError, match="Unknown layer preset"):
        get_preset("not-a-preset")


def test_all_presets_have_consistent_keys():
    expected = set(SemanticLayer)
    for preset in PRESETS.values():
        assert set(preset.layers) == expected, f"{preset.short_id} missing layers"
