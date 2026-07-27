"""Sokkia SDR + Nikon RAW reader smoke tests."""

from __future__ import annotations

from meridian.adapters.instruments.nikon_raw import NikonRawDriver
from meridian.adapters.instruments.sokkia_sdr import SokkiaSDRDriver

# ── Sokkia ─────────────────────────────────────────────────────────────────


SOKKIA_SAMPLE = """\
00NMSDR331V03 100
07 1.500
09 P1 P2 0900000
08 P3 0900000 0900000 100.000
"""


def test_sokkia_can_read(tmp_path):
    p = tmp_path / "x.sdr"
    p.write_text(SOKKIA_SAMPLE)
    assert SokkiaSDRDriver().can_read(p)


def test_sokkia_parses_setup_and_observation(tmp_path):
    p = tmp_path / "x.sdr"
    p.write_text(SOKKIA_SAMPLE)
    res = SokkiaSDRDriver().read(p)
    assert len(res.setups) >= 1
    kinds = {o.kind.value for o in res.observations}
    # We should at least get a horizontal-distance / angle pair.
    assert kinds & {"horizontal_angle", "slope_distance", "vertical_angle"}


# ── Nikon ──────────────────────────────────────────────────────────────────


NIKON_SAMPLE = """\
JE,JOB1,1,2026-05-01
ST,P1,P0,1.500,0-00-00,Setup A
SS,P2,90-00-00,90-00-00,100.000,1.500,
SS,P3,180-00-00,90-00-00,100.000,1.500,
"""


def test_nikon_can_read(tmp_path):
    p = tmp_path / "x.raw"
    p.write_text(NIKON_SAMPLE)
    assert NikonRawDriver().can_read(p)


def test_nikon_parses_two_observations(tmp_path):
    p = tmp_path / "x.raw"
    p.write_text(NIKON_SAMPLE)
    res = NikonRawDriver().read(p)
    assert len(res.setups) == 1
    assert res.setups[0].occupied_point == "P1"
    # Each SS produces HA + VA + SD = 3 observations × 2 sideshots = 6.
    assert len(res.observations) == 6
    assert {o.to_point for o in res.observations} == {"P2", "P3"}
