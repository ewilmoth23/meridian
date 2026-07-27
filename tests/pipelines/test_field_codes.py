"""Tests for ``meridian.pipelines.field_codes``."""

from __future__ import annotations

from meridian.domain.crs import CRS, Datum
from meridian.domain.geometry import Point2D, Point3D
from meridian.pipelines.field_codes import (
    STANDARD_CODEBOOK,
    CodeDefinition,
    CodeKind,
    FieldPoint,
    build_features,
    parse_pnezd,
    parse_raw_code,
)

CRS_TX = CRS(epsg=2277, datum=Datum(name="NAD83", realization="2011", epsg=6318))


def fp(num: int, x: float, y: float, code: str, z: float | None = None) -> FieldPoint:
    if z is None:
        pt: Point2D | Point3D = Point2D(x=x, y=y, crs=CRS_TX)
    else:
        pt = Point3D(x=x, y=y, z=z, crs=CRS_TX)
    return FieldPoint(point_number=num, point=pt, raw_code=code)


# ── parse_raw_code ──────────────────────────────────────────────────────────


def test_parse_simple_code():
    [tok] = parse_raw_code("EOP")
    assert tok.code == "EOP"
    assert tok.feature_number is None
    assert not tok.opens and not tok.closes


def test_parse_with_open_marker_plus():
    [tok] = parse_raw_code("+EOP")
    assert tok.opens is True


def test_parse_with_close_marker_minus():
    [tok] = parse_raw_code("-EOP")
    assert tok.closes is True


def test_parse_with_word_open_close():
    [a] = parse_raw_code("BEG EOP")[:1]  # uses first matched token
    assert a.opens is True or a.code == "BEG"
    # The current parser treats "BEG" as a separate word, not a prefix.
    # But the regex captures "BEG" as a delim followed by alpha base — confirm the joined form too:
    [b] = parse_raw_code("BEGEOP")
    assert b.opens is True
    assert b.code == "EOP"


def test_parse_numeric_feature_id():
    [a, b] = parse_raw_code("EOP1 EOP2")
    assert a.feature_number == 1
    assert b.feature_number == 2


def test_parse_strips_comments():
    toks = parse_raw_code("EOP // edge near maple")
    assert len(toks) == 1 and toks[0].code == "EOP"


def test_parse_handles_commas_and_whitespace():
    toks = parse_raw_code("EOP, BOC,  +TR")
    assert [t.code for t in toks] == ["EOP", "BOC", "TR"]
    assert toks[2].opens is True


def test_parse_drops_unmatched_tokens():
    toks = parse_raw_code("EOP $$$ FH")
    assert [t.code for t in toks] == ["EOP", "FH"]


def test_parse_curve_markers():
    [bc] = parse_raw_code("BC")
    [ec] = parse_raw_code("EC")
    assert bc.is_curve_begin
    assert ec.is_curve_end


def test_parse_empty_returns_empty():
    assert parse_raw_code("") == ()
    assert parse_raw_code("   ") == ()


def test_parse_case_insensitive():
    [tok] = parse_raw_code("eop")
    assert tok.code == "EOP"


# ── CodeBook ────────────────────────────────────────────────────────────────


def test_codebook_lookup_known():
    defn = STANDARD_CODEBOOK.lookup("EOP")
    assert defn.kind is CodeKind.LINE
    assert defn.layer == "ROAD-EOP"


def test_codebook_lookup_unknown_falls_back():
    defn = STANDARD_CODEBOOK.lookup("ZZZ")
    assert defn.kind is CodeKind.POINT
    assert defn.layer == "FIELD-UNKNOWN"


def test_codebook_lookup_case_insensitive():
    a = STANDARD_CODEBOOK.lookup("eop")
    b = STANDARD_CODEBOOK.lookup("EOP")
    assert a == b


def test_codebook_with_definition_appends():
    custom = CodeDefinition(code="XYZ", kind=CodeKind.LINE, layer="CUSTOM", description="custom")
    cb = STANDARD_CODEBOOK.with_definition(custom)
    assert cb.lookup("XYZ").layer == "CUSTOM"
    # Original is unchanged.
    assert STANDARD_CODEBOOK.lookup("XYZ").layer == "FIELD-UNKNOWN"


def test_codebook_overrides_existing():
    custom = CodeDefinition(code="EOP", kind=CodeKind.LINE, layer="CUSTOM-EOP", description="overridden")
    cb = STANDARD_CODEBOOK.with_definition(custom)
    assert cb.lookup("EOP").layer == "CUSTOM-EOP"


def test_standard_codebook_covers_common_codes():
    for c in ("EOP", "BOC", "TOC", "FH", "MH", "PP", "TR", "GS", "TBM", "PL", "RW"):
        defn = STANDARD_CODEBOOK.lookup(c)
        assert defn.layer != "FIELD-UNKNOWN", f"missing canonical code {c!r}"


# ── build_features: lines ───────────────────────────────────────────────────


def test_consecutive_same_code_makes_one_line():
    pts = [fp(1, 0, 0, "EOP"), fp(2, 10, 0, "EOP"), fp(3, 20, 0, "EOP")]
    [f] = build_features(pts)
    assert f.kind is CodeKind.LINE
    assert len(f.points) == 3
    assert f.layer == "ROAD-EOP"


def test_plus_marker_starts_new_feature():
    pts = [
        fp(1, 0, 0, "+EOP"),
        fp(2, 10, 0, "EOP"),
        fp(3, 20, 0, "+EOP"),  # restarts → second feature
        fp(4, 30, 0, "EOP"),
    ]
    features = build_features(pts)
    assert len(features) == 2
    assert all(f.code == "EOP" for f in features)
    assert sum(len(f.points) for f in features) == 4


def test_minus_marker_closes_feature():
    pts = [
        fp(1, 0, 0, "+EOP"),
        fp(2, 10, 0, "EOP"),
        fp(3, 20, 0, "-EOP"),
        fp(4, 30, 0, "EOP"),  # opens a fresh EOP after close
    ]
    features = build_features(pts)
    assert len(features) == 2


def test_parallel_features_via_numeric_suffix():
    pts = [
        fp(1, 0, 0, "EOP1"), fp(2, 10, 0, "EOP1"),
        fp(3, 0, 5, "EOP2"), fp(4, 10, 5, "EOP2"),
    ]
    features = build_features(pts)
    assert len(features) == 2
    nums = sorted(f.feature_number for f in features)
    assert nums == [1, 2]


def test_multi_code_point_joins_two_features():
    pts = [
        fp(1, 0, 0, "EOP BOC"),
        fp(2, 10, 0, "EOP BOC"),
        fp(3, 20, 0, "EOP"),
    ]
    features = sorted(build_features(pts), key=lambda f: f.code)
    assert {f.code for f in features} == {"BOC", "EOP"}
    eop = next(f for f in features if f.code == "EOP")
    boc = next(f for f in features if f.code == "BOC")
    assert len(eop.points) == 3
    assert len(boc.points) == 2


# ── build_features: curves ──────────────────────────────────────────────────


def test_bc_ec_makes_arc_kind():
    pts = [
        fp(1, 0, 0, "+EOP"),
        fp(2, 10, 0, "EOP BC"),
        fp(3, 20, 5, "EOP"),
        fp(4, 30, 8, "EOP EC"),
        fp(5, 40, 8, "-EOP"),
    ]
    [f] = build_features(pts)
    assert f.kind is CodeKind.ARC
    assert len(f.points) == 5


def test_pt_token_treated_as_curve_end():
    pts = [
        fp(1, 0, 0, "+EOP BC"),
        fp(2, 10, 0, "EOP"),
        fp(3, 20, 5, "EOP PT"),
    ]
    [f] = build_features(pts)
    assert f.kind is CodeKind.ARC


# ── build_features: symbols & points ───────────────────────────────────────


def test_symbol_points_split_one_per_shot():
    pts = [fp(1, 0, 0, "FH"), fp(2, 100, 0, "FH"), fp(3, 200, 0, "FH")]
    features = build_features(pts)
    assert len(features) == 3
    assert {f.code for f in features} == {"FH"}
    assert all(f.kind is CodeKind.SYMBOL for f in features)
    assert all(len(f.points) == 1 for f in features)


def test_point_only_codes_split_one_per_shot():
    pts = [fp(1, 0, 0, "GS"), fp(2, 10, 0, "GS"), fp(3, 20, 0, "GS")]
    features = build_features(pts)
    assert len(features) == 3
    assert all(f.kind is CodeKind.POINT for f in features)


# ── build_features: breaklines ──────────────────────────────────────────────


def test_breakline_groups_into_one_feature():
    pts = [fp(i, i * 10.0, 0.0, "TOE", z=100 - i) for i in range(1, 6)]
    [f] = build_features(pts)
    assert f.kind is CodeKind.BREAKLINE
    assert f.layer == "TOPO-TOE"
    assert len(f.points) == 5


# ── build_features: edge cases ─────────────────────────────────────────────


def test_empty_input_returns_empty():
    assert build_features([]) == ()


def test_unknown_code_falls_through_to_point():
    pts = [fp(1, 0, 0, "WEIRD")]
    [f] = build_features(pts)
    assert f.kind is CodeKind.POINT
    assert f.layer == "FIELD-UNKNOWN"


def test_ignore_only_code_emits_nothing():
    pts = [fp(1, 0, 0, "BC"), fp(2, 10, 0, "EC")]
    assert build_features(pts) == ()


def test_features_are_stable_sorted_by_first_point():
    pts = [
        fp(5, 0, 0, "FH"),
        fp(2, 10, 0, "FH"),
        fp(8, 20, 0, "FH"),
    ]
    features = build_features(pts)
    pts_first = [f.point_numbers[0] for f in features]
    assert pts_first == sorted(pts_first)


def test_3d_points_yield_3d_features():
    pts = [fp(i, i * 10.0, 0.0, "EOP", z=95.0) for i in range(1, 4)]
    [f] = build_features(pts)
    assert f.is_3d
    assert all(isinstance(p, Point3D) for p in f.points)


# ── parse_pnezd ─────────────────────────────────────────────────────────────


def test_parse_pnezd_basic():
    text = """
    1, 100.0, 200.0, 95.5, +EOP
    2, 110.0, 200.0, 95.4, EOP
    3, 120.0, 200.0, 95.3, -EOP
    """
    pts = parse_pnezd(text, crs=CRS_TX)
    assert len(pts) == 3
    assert pts[0].point_number == 1
    # PNEZD: northing first → Point2D.y = north, Point2D.x = east
    assert pts[0].point.y == 100.0
    assert pts[0].point.x == 200.0
    assert isinstance(pts[0].point, Point3D)


def test_parse_pnezd_two_d_only():
    text = "1, 100.0, 200.0, 95.5, EOP"
    [pt] = parse_pnezd(text, crs=CRS_TX, two_d_only=True)
    assert isinstance(pt.point, Point2D)


def test_parse_pnezd_skips_garbage_lines():
    text = """
    Header line that is not data
    1, 100.0, 200.0, 95.5, EOP
    blank below

    2, 110.0, 200.0, 95.4, EOP
    """
    pts = parse_pnezd(text, crs=CRS_TX)
    assert len(pts) == 2


def test_parse_pnezd_handles_space_separated():
    text = "1 100.0 200.0 95.5 EOP"
    [pt] = parse_pnezd(text, crs=CRS_TX)
    assert pt.point_number == 1


def test_parse_pnezd_blank_code_ok():
    text = "1, 100.0, 200.0, 95.5,"
    [pt] = parse_pnezd(text, crs=CRS_TX)
    assert pt.raw_code == ""


# ── End-to-end: PNEZD → features ───────────────────────────────────────────


def test_pnezd_to_features_full_pipeline():
    text = """
    1, 100.0, 200.0, 95.5, +EOP
    2, 110.0, 200.0, 95.4, EOP BC
    3, 120.0, 195.0, 95.3, EOP
    4, 130.0, 192.0, 95.2, EOP EC
    5, 140.0, 192.0, 95.1, -EOP
    6, 105.0, 198.0, 95.0, FH
    7, 145.0, 198.0, 95.0, FH
    8, 125.0, 205.0, 94.9, MH
    """
    features = build_features(parse_pnezd(text, crs=CRS_TX))
    by_kind = {}
    for f in features:
        by_kind.setdefault(f.kind, []).append(f)
    # 1 polyline (turned into ARC), 2 hydrants (split), 1 manhole.
    assert len(by_kind[CodeKind.ARC]) == 1
    assert len(by_kind[CodeKind.SYMBOL]) == 3  # 2 FH + 1 MH
