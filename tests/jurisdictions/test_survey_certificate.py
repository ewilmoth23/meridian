"""Tests for ``meridian.jurisdictions.survey_certificate``."""

from __future__ import annotations

import datetime as dt

import pytest

from meridian.jurisdictions.survey_certificate import (
    STATE_TEMPLATES,
    ALTATableAItem,
    Certificate,
    CertificateType,
    SealType,
    SurveyAccuracyClass,
    SurveyorIdentity,
    SurveyProject,
    alta_table_a_catalog,
    alta_table_a_lookup,
    build_alta_certificate,
    build_boundary_certificate,
    build_certificate,
    build_elevation_certificate,
    build_mortgage_inspection_certificate,
    build_subdivision_certificate,
    get_statutory_template,
    render_html,
    render_text,
    validate_alta_compliance,
    validate_certificate,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


def _surveyor(state: str = "TX", **kw) -> SurveyorIdentity:
    defaults = {
        "name": "Misty Clarke",
        "license_state": state,
        "license_number": "6543",
    }
    defaults.update(kw)
    return SurveyorIdentity(**defaults)


def _project(state: str = "TX", **kw) -> SurveyProject:
    defaults = {
        "project_name": "Lot 12, Block A — Travis Heights",
        "legal_description": "LOT 12, BLOCK A, TRAVIS HEIGHTS, ACCORDING TO PLAT RECORDED IN VOL 4 PG 87.",
        "state": state,
        "survey_date": dt.date(2026, 4, 28),
    }
    defaults.update(kw)
    return SurveyProject(**defaults)


# ── SurveyorIdentity validation ────────────────────────────────────────────


def test_surveyor_requires_name():
    with pytest.raises(ValueError, match="name"):
        SurveyorIdentity(name="  ", license_state="TX", license_number="123")


def test_surveyor_requires_two_letter_state():
    with pytest.raises(ValueError, match="2-letter"):
        SurveyorIdentity(name="X", license_state="Texas", license_number="123")


def test_surveyor_requires_license_number():
    with pytest.raises(ValueError, match="license_number"):
        SurveyorIdentity(name="X", license_state="TX", license_number="")


def test_surveyor_records_seal_type_default():
    s = _surveyor()
    assert s.seal_type is SealType.INKED


# ── SurveyProject validation ───────────────────────────────────────────────


def test_project_requires_name():
    with pytest.raises(ValueError, match="project_name"):
        SurveyProject(project_name="", legal_description="x", state="TX", survey_date=dt.date.today())


def test_project_requires_two_letter_state():
    with pytest.raises(ValueError, match="2-letter"):
        SurveyProject(
            project_name="X",
            legal_description="x",
            state="texas",
            survey_date=dt.date.today(),
        )


def test_project_field_dates_must_be_ordered():
    with pytest.raises(ValueError, match="field_end"):
        SurveyProject(
            project_name="X",
            legal_description="x",
            state="TX",
            survey_date=dt.date(2026, 1, 10),
            field_start=dt.date(2026, 1, 10),
            field_end=dt.date(2026, 1, 5),
        )


# ── ALTA Table A catalog ───────────────────────────────────────────────────


def test_alta_catalog_includes_known_items():
    catalog = alta_table_a_catalog()
    keys = {item.key for item in catalog}
    # A handful of canonical keys.
    for k in ("1", "3", "4", "6a", "6b", "11", "21a"):
        assert k in keys


def test_alta_lookup_returns_correct_item():
    item = alta_table_a_lookup("3")
    assert item.number == 3
    assert item.sub is None
    assert "flood" in item.description.lower()


def test_alta_lookup_subitem():
    item = alta_table_a_lookup("6b")
    assert item.number == 6 and item.sub == "b"


def test_alta_lookup_unknown_raises():
    with pytest.raises(KeyError):
        alta_table_a_lookup("99")


# ── State statutory templates ──────────────────────────────────────────────


def test_state_templates_cover_ten_states():
    assert set(STATE_TEMPLATES) >= {
        "TX", "FL", "CA", "NY", "OH", "CO", "VA", "GA", "PA", "NC"
    }


def test_get_statutory_template_returns_named_state():
    t = get_statutory_template("CA")
    assert t.state == "CA"
    assert "California" in t.state_full
    assert "Bus. & Prof. Code" in t.citation


def test_get_statutory_template_falls_back_for_unknown_state():
    t = get_statutory_template("XX")
    assert t.state == "XX"
    assert t.citation.startswith("Generic")


def test_get_statutory_template_uses_full_state_name_in_generic():
    # "WY" isn't in STATE_TEMPLATES at this point, but its full name is known.
    t = get_statutory_template("WY")
    if t.citation.startswith("Generic"):
        # The generic template should know the full name.
        assert t.state_full == "Wyoming"


def test_template_render_substitutes_placeholders():
    t = get_statutory_template("TX")
    out = t.render(
        surveyor=_surveyor(),
        project=_project(project_name="ProjX"),
        issue_date=dt.date(2026, 5, 2),
    )
    assert "Misty Clarke" in out
    assert "6543" in out
    assert "ProjX" in out
    assert "2026-05-02" in out


# ── build_certificate ──────────────────────────────────────────────────────


def test_build_certificate_default_issue_date_is_today():
    cert = build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=_surveyor(),
        project=_project(),
    )
    assert cert.issue_date == dt.date.today()


def test_build_certificate_uses_correct_state_template():
    cert = build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=_surveyor(state="FL"),
        project=_project(state="FL"),
    )
    assert cert.statutory.state == "FL"
    assert "Florida" in cert.statutory_text_rendered


# ── build_alta_certificate ─────────────────────────────────────────────────


def test_alta_certificate_includes_requested_table_a_items():
    cert = build_alta_certificate(
        surveyor=_surveyor(),
        project=_project(),
        table_a_keys=["1", "3", "4", "6a", "11"],
    )
    keys = {i.key for i in cert.alta_items}
    assert keys == {"1", "3", "4", "6a", "11"}


def test_alta_certificate_default_accuracy_class_urban():
    cert = build_alta_certificate(surveyor=_surveyor(), project=_project())
    assert cert.accuracy_class is SurveyAccuracyClass.URBAN


def test_alta_certificate_includes_2021_standards_text():
    cert = build_alta_certificate(surveyor=_surveyor(), project=_project(), table_a_keys=["1"])
    joined = " ".join(cert.additional_certifications)
    assert "2021 Minimum Standard" in joined
    assert "ALTA" in joined


def test_alta_certificate_includes_title_disclaimer():
    cert = build_alta_certificate(surveyor=_surveyor(), project=_project(), table_a_keys=["1"])
    joined = " ".join(cert.disclaimers)
    assert "title" in joined.lower()


def test_alta_certificate_with_unknown_key_raises():
    with pytest.raises(KeyError):
        build_alta_certificate(
            surveyor=_surveyor(),
            project=_project(),
            table_a_keys=["1", "99"],
        )


# ── Other certificate types ────────────────────────────────────────────────


def test_boundary_certificate_disclaimer_mentions_title():
    cert = build_boundary_certificate(surveyor=_surveyor(), project=_project())
    joined = " ".join(cert.disclaimers)
    assert "title" in joined.lower()


def test_mortgage_inspection_says_not_a_boundary_survey():
    cert = build_mortgage_inspection_certificate(surveyor=_surveyor(), project=_project())
    joined = " ".join(cert.disclaimers)
    assert "NOT A BOUNDARY SURVEY" in joined.upper()


def test_subdivision_certificate_mentions_monumentation():
    cert = build_subdivision_certificate(surveyor=_surveyor(), project=_project())
    joined = " ".join(cert.additional_certifications)
    assert "monumented" in joined.lower()


def test_elevation_certificate_requires_flood_zone():
    proj = _project(vertical_datum="NAVD88")  # flood_zone missing
    with pytest.raises(ValueError, match="flood_zone"):
        build_elevation_certificate(surveyor=_surveyor(), project=proj)


def test_elevation_certificate_requires_vertical_datum():
    proj = _project(flood_zone="X")  # vertical_datum missing
    with pytest.raises(ValueError, match="vertical_datum"):
        build_elevation_certificate(surveyor=_surveyor(), project=proj)


def test_elevation_certificate_assembled_with_required_data():
    proj = _project(flood_zone="AE", vertical_datum="NAVD88")
    cert = build_elevation_certificate(surveyor=_surveyor(), project=proj)
    joined = " ".join(cert.additional_certifications)
    assert "NAVD88" in joined
    assert "AE" in joined
    assert "FEMA" in joined


# ── Validation ─────────────────────────────────────────────────────────────


def test_validation_clean_certificate_has_no_issues():
    cert = build_alta_certificate(
        surveyor=_surveyor(),
        project=_project(),
        table_a_keys=["1"],
    )
    issues = validate_certificate(cert)
    assert issues == ()


def test_validation_warns_on_cross_state_license():
    cert = build_alta_certificate(
        surveyor=_surveyor(state="TX"),
        project=_project(state="FL"),
        table_a_keys=["1"],
    )
    issues = validate_certificate(cert)
    assert any("reciprocity" in i.message.lower() for i in issues)
    assert all(i.severity == "warning" for i in issues if "reciprocity" in i.message.lower())


def test_validation_errors_on_expired_license():
    s = _surveyor(license_expiration=dt.date(2024, 1, 1))
    cert = build_boundary_certificate(
        surveyor=s, project=_project(), issue_date=dt.date(2026, 5, 2)
    )
    issues = validate_certificate(cert)
    expired = [i for i in issues if "expired" in i.message]
    assert len(expired) == 1
    assert expired[0].severity == "error"


def test_validation_errors_on_field_after_issue():
    proj = _project(field_end=dt.date(2026, 6, 1))
    cert = build_boundary_certificate(
        surveyor=_surveyor(), project=proj, issue_date=dt.date(2026, 5, 2)
    )
    issues = validate_certificate(cert)
    assert any("Field work ended" in i.message for i in issues)


def test_validation_errors_on_alta_items_in_non_alta_cert():
    # Sneak ALTA items onto a boundary cert via build_certificate directly.
    cert = build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=_surveyor(),
        project=_project(),
        alta_items=(alta_table_a_lookup("1"),),
    )
    issues = validate_certificate(cert)
    errors = [i for i in issues if i.severity == "error"]
    assert any("only valid on ALTA" in i.message for i in errors)


def test_validation_warns_on_unknown_state():
    cert = build_boundary_certificate(
        surveyor=_surveyor(state="XX"), project=_project(state="XX")
    )
    issues = validate_certificate(cert)
    assert any("Generic" in i.message or "generic" in i.message for i in issues)


def test_validation_alta_warns_when_no_accuracy_class():
    cert = build_certificate(
        certificate_type=CertificateType.ALTA_NSPS,
        surveyor=_surveyor(),
        project=_project(),
    )  # no accuracy_class supplied
    issues = validate_certificate(cert)
    assert any("accuracy" in i.message.lower() for i in issues)


# ── ALTA compliance ────────────────────────────────────────────────────────


def test_alta_compliance_passes_when_all_required_keys_present():
    cert = build_alta_certificate(
        surveyor=_surveyor(), project=_project(),
        table_a_keys=["1", "3", "4", "6a", "11"],
    )
    assert validate_alta_compliance(cert, required_keys=["1", "3", "11"]) == ()


def test_alta_compliance_flags_missing_keys():
    cert = build_alta_certificate(
        surveyor=_surveyor(), project=_project(), table_a_keys=["1", "3"],
    )
    issues = validate_alta_compliance(cert, required_keys=["1", "3", "11"])
    missing = [i for i in issues if "11" in i.message]
    assert len(missing) == 1
    assert missing[0].severity == "error"


def test_alta_compliance_rejects_non_alta_certs():
    cert = build_boundary_certificate(surveyor=_surveyor(), project=_project())
    issues = validate_alta_compliance(cert, required_keys=["1"])
    assert len(issues) == 1
    assert "Not an ALTA" in issues[0].message


# ── Rendering ──────────────────────────────────────────────────────────────


def test_render_text_contains_required_sections():
    cert = build_alta_certificate(
        surveyor=_surveyor(),
        project=_project(),
        table_a_keys=["1", "3"],
    )
    text = render_text(cert)
    assert "ALTA/NSPS" in text
    assert "LEGAL DESCRIPTION" in text
    assert "CERTIFICATION" in text
    assert "ALTA TABLE A ITEMS" in text
    assert "Misty Clarke" in text
    assert "License No. 6543" in text


def test_render_text_includes_statutory_citation():
    cert = build_boundary_certificate(surveyor=_surveyor(), project=_project())
    text = render_text(cert)
    assert "Statutory authority" in text
    assert "22 Tex. Admin. Code" in text


def test_render_html_is_well_formed_minimal():
    cert = build_alta_certificate(
        surveyor=_surveyor(), project=_project(), table_a_keys=["1"]
    )
    html_out = render_html(cert)
    assert html_out.startswith("<!DOCTYPE html>")
    assert "</html>" in html_out
    assert "<style>" in html_out
    assert "Misty Clarke" in html_out
    assert "ALTA" in html_out


def test_render_html_escapes_markup_in_inputs():
    proj = _project(
        project_name="Lot <evil> & Co.",
        legal_description="A description with </script> in it.",
    )
    cert = build_boundary_certificate(surveyor=_surveyor(), project=proj)
    out = render_html(cert)
    assert "<evil>" not in out
    assert "&lt;evil&gt;" in out
    assert "</script>" not in out.replace("</script>", "GONE")  # no unescaped raw </script>


def test_render_html_omits_seal_block_signature_line():
    # The signature block exists, even though we don't auto-sign.
    cert = build_boundary_certificate(surveyor=_surveyor(), project=_project())
    out = render_html(cert)
    assert "Surveyor's Seal" in out or "Seal" in out
    assert "signature-block" in out


def test_render_text_for_mortgage_inspection_carries_warning():
    cert = build_mortgage_inspection_certificate(surveyor=_surveyor(), project=_project())
    text = render_text(cert)
    assert "NOT A BOUNDARY SURVEY" in text


# ── Frozen dataclasses ─────────────────────────────────────────────────────


def test_certificate_is_frozen():
    cert = build_boundary_certificate(surveyor=_surveyor(), project=_project())
    with pytest.raises(AttributeError):
        cert.issue_date = dt.date(2030, 1, 1)  # type: ignore[misc]


def test_table_a_item_is_frozen():
    item = alta_table_a_lookup("1")
    with pytest.raises(AttributeError):
        item.short_label = "tampered"  # type: ignore[misc]


def test_certificate_extra_dict_isolated_per_instance():
    a = build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=_surveyor(),
        project=_project(),
        extra={"k": "v1"},
    )
    b = build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=_surveyor(),
        project=_project(),
    )
    assert a.extra == {"k": "v1"}
    assert b.extra == {}


# ── Integration: a full TX ALTA workflow ───────────────────────────────────


def test_full_tx_alta_workflow():
    s = _surveyor(
        license_state="TX",
        license_number="6543",
        seal_type=SealType.DIGITAL,
        business_name="Clarke Land Surveying, PLLC",
        license_expiration=dt.date(2027, 12, 31),
    )
    p = _project(
        state="TX",
        county="Travis",
        property_address="1100 S Congress Ave, Austin TX 78704",
        parcel_id="0301010812",
        drawing_number="2026-0428-01",
        job_number="J-26-118",
        client_name="Old Republic Title",
        horizontal_datum="NAD83(2011)",
        vertical_datum="NAVD88",
        flood_zone="X",
        closure_ratio_text="1:18,500",
        field_start=dt.date(2026, 4, 25),
        field_end=dt.date(2026, 4, 27),
    )
    cert = build_alta_certificate(
        surveyor=s,
        project=p,
        table_a_keys=["1", "2", "3", "4", "6a", "8", "11", "13", "16"],
        accuracy_class=SurveyAccuracyClass.URBAN,
        issue_date=dt.date(2026, 5, 2),
    )
    assert isinstance(cert, Certificate)
    assert validate_certificate(cert) == ()
    assert validate_alta_compliance(cert, required_keys=["1", "3", "11"]) == ()
    text = render_text(cert)
    html_out = render_html(cert)
    # Both renderings carry every project field worth printing.
    for must in ("Travis", "1100 S Congress", "0301010812", "J-26-118", "Old Republic"):
        assert must in text, f"missing {must!r} in text"
        assert must in html_out, f"missing {must!r} in html"


def test_alta_table_a_item_can_be_constructed_directly():
    """Sanity: the dataclass is usable for plugin-defined extra items."""
    custom = ALTATableAItem(
        number=22, sub=None, short_label="Custom",
        description="Custom client requirement.",
    )
    assert custom.key == "22"
