"""DeedLM corpus + synthetic tests."""

from __future__ import annotations

import json
import random

import pytest

from meridian.ai.deedlm import CorpusBuilder, generate_synthetic_deed
from meridian.ai.deedlm.inference import parse_deedlm_response


def test_synthetic_deeds_render_for_each_dialect():
    rng = random.Random(7)
    for dialect in ("texas_vara", "ne_rod_pole", "plss_aliquot", "modern_ca"):
        text = generate_synthetic_deed(dialect, rng=rng)
        assert isinstance(text, str)
        assert len(text) > 50


def test_corpus_builder_writes_splits(tmp_path):
    builder = CorpusBuilder(out_dir=tmp_path)
    entries = list(builder.ingest_synthetic(50, seed=1))
    paths = builder.write_jsonl(entries)
    assert paths["train"].exists()
    assert paths["val"].exists()
    assert paths["test"].exists()
    # Confirm each line is JSON parseable.
    train = paths["train"].read_text(encoding="utf-8").splitlines()
    assert all(json.loads(line) for line in train)
    assert builder.stats.total_in == 50


def test_corpus_builder_dedupes_repeated_inputs(tmp_path):
    builder = CorpusBuilder(out_dir=tmp_path)
    fixed = "Beginning at the POB; thence N 0°00'00\" E 100 meters; thence N 90°00'00\" E 100 meters; thence S 0°00'00\" W 100 meters; thence S 90°00'00\" W 100 meters to the POB."
    seen = set()
    entries = []
    for _ in range(5):
        entry = builder._make_entry(fixed, source="fixed", jurisdiction="TX")
        if entry is not None:
            entries.append(entry)
    assert len(entries) == 1   # rest dedupe out
    assert builder.stats.duplicates == 4


def test_parse_deedlm_response_extracts_json():
    raw = "Sure!\n```json\n{\"calls\": [], \"point_of_beginning_text\": null}\n```"
    parsed = parse_deedlm_response(raw)
    assert "calls" in parsed


def test_parse_deedlm_response_rejects_non_json():
    with pytest.raises(ValueError):
        parse_deedlm_response("nothing parseable here")
