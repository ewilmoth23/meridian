"""Survey-certificate generator — assembled, signable certifications.

Every plat or survey deliverable that crosses a desk has to carry a signed
certification: the surveyor swears to the work, cites the statute(s) under
which they're licensed, and (for ALTA/NSPS land-title surveys) checks off
the optional Table A items their client requested.

This module turns a structured ``SurveyorIdentity`` + ``SurveyProject`` into
a :class:`Certificate` carrying the right statutory boilerplate for the
project's state, the right ALTA Table A clauses, and disclaimers
appropriate to the certificate type. Output is an HTML and/or plain-text
document the surveyor reviews, prints, signs, and seals.

What this module is *not*: it does not apply digital seals or sign anything
on the surveyor's behalf — that's the surveyor's professional act, and is
deliberately kept out of code. ``surveyor.digital_signature_id`` is recorded
on the certificate as a *reference* to a signature applied by the
:mod:`meridian.truthchain` keystore in a separate, audited step.

State coverage: ten states with documented certification language (TX, FL,
CA, NY, OH, CO, VA, GA, PA, NC). Other states fall back to a generic
template with the state's name interpolated. Adding a state means appending
one entry to :data:`STATE_TEMPLATES`.

ALTA coverage: the 2021 standard's Table A (21 numbered items, several with
sub-items). Items the surveyor wants to certify are passed in by ID; the
generator produces the matching boilerplate text.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from enum import Enum

# ── Enums ───────────────────────────────────────────────────────────────────


class CertificateType(str, Enum):
    BOUNDARY = "boundary"
    ALTA_NSPS = "alta_nsps"
    MORTGAGE_INSPECTION = "mortgage_inspection"
    TOPOGRAPHIC = "topographic"
    AS_BUILT = "as_built"
    SUBDIVISION = "subdivision"
    ELEVATION = "elevation"
    LOT_SURVEY = "lot_survey"
    ROUTE = "route"
    CONSTRUCTION_STAKING = "construction_staking"


class SurveyAccuracyClass(str, Enum):
    """ALTA/NSPS positional accuracy classes (2021)."""

    URBAN = "urban"
    SUBURBAN = "suburban"
    RURAL = "rural"
    MOUNTAIN_MARSH = "mountain_marsh"


class SealType(str, Enum):
    EMBOSSED = "embossed"
    INKED = "inked"
    DIGITAL = "digital"
    NONE = "none"


# ── Records ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SurveyorIdentity:
    """A licensed land surveyor's professional identity."""

    name: str
    license_state: str           # 2-letter postal code, e.g. "TX"
    license_number: str
    seal_type: SealType = SealType.INKED
    business_name: str | None = None
    business_address: str | None = None
    license_expiration: dt.date | None = None
    digital_signature_id: str | None = None  # truthchain key reference, never the key itself
    email: str | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Surveyor name is required.")
        if not re.fullmatch(r"[A-Za-z]{2}", self.license_state):
            raise ValueError(
                f"license_state must be a 2-letter code, got {self.license_state!r}."
            )
        if not self.license_number.strip():
            raise ValueError("license_number is required.")


@dataclass(frozen=True, slots=True)
class SurveyProject:
    """The project being certified."""

    project_name: str
    legal_description: str
    state: str                              # where the property is — drives statutory text
    survey_date: dt.date
    property_address: str | None = None
    parcel_id: str | None = None            # APN / county tax id
    county: str | None = None
    field_start: dt.date | None = None
    field_end: dt.date | None = None
    drawing_scale: str | None = None        # "1\" = 50'" or "1:600"
    drawing_number: str | None = None
    job_number: str | None = None
    client_name: str | None = None
    horizontal_datum: str | None = None     # "NAD83(2011)"
    vertical_datum: str | None = None       # "NAVD88"
    benchmark: str | None = None
    flood_zone: str | None = None           # FEMA designation; also see Item 3
    closure_ratio_text: str | None = None   # "1:15,000"

    def __post_init__(self) -> None:
        if not self.project_name.strip():
            raise ValueError("project_name is required.")
        if not re.fullmatch(r"[A-Za-z]{2}", self.state):
            raise ValueError(f"state must be a 2-letter code, got {self.state!r}.")
        if self.field_start and self.field_end and self.field_end < self.field_start:
            raise ValueError("field_end cannot be before field_start.")


# ── ALTA/NSPS 2021 Table A ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ALTATableAItem:
    """A single Table A optional item from the ALTA/NSPS 2021 standard."""

    number: int                  # 1..21
    sub: str | None              # "a", "b", "c" for sub-items, else None
    short_label: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.number}{self.sub}" if self.sub else str(self.number)


# Canonical Table A list, condensed (each item's *full* boilerplate is in the
# rendered HTML/text; the description here is human-readable shorthand).
_ALTA_TABLE_A: tuple[ALTATableAItem, ...] = (
    ALTATableAItem(1, None, "Monuments at corners",
        "Monuments placed (or referenced) at all major corners of the boundary."),
    ALTATableAItem(2, None, "Address(es) shown",
        "Address(es) of surveyed property shown on the plat."),
    ALTATableAItem(3, None, "Flood zone classification",
        "Flood zone classification, FIRM panel number, and date shown."),
    ALTATableAItem(4, None, "Gross land area",
        "Gross land area shown on the face of the plat."),
    ALTATableAItem(5, None, "Vertical relief",
        "Vertical relief shown by spot elevations or contours."),
    ALTATableAItem(6, "a", "Current zoning",
        "Current zoning classification per appropriate source."),
    ALTATableAItem(6, "b", "Zoning report",
        "Zoning report findings (setbacks, height, parking, floor space ratio)."),
    ALTATableAItem(7, "a", "Building exterior dimensions",
        "Exterior dimensions of all buildings at ground level."),
    ALTATableAItem(7, "b", "Building square footage",
        "Square footage of buildings (gross above-grade)."),
    ALTATableAItem(7, "c", "Measured height",
        "Measured height of buildings above grade."),
    ALTATableAItem(8, None, "Substantial features",
        "Substantial features observed on the property (parking, retaining walls, signs, etc.)."),
    ALTATableAItem(9, None, "Striped parking",
        "Number and type of striped parking spaces, including handicap-accessible."),
    ALTATableAItem(10, None, "Division wall determination",
        "Determination of party walls / division walls between adjoining buildings."),
    ALTATableAItem(11, None, "Plottable utilities",
        "Locations of plottable utilities by observation and per available records."),
    ALTATableAItem(12, None, "Government surveys",
        "Government agency surveys (rights-of-way, easements) referenced."),
    ALTATableAItem(13, None, "Adjoining owners",
        "Names of adjoining owners per current tax records."),
    ALTATableAItem(14, None, "Distance to nearest street",
        "Distance to nearest intersecting street as observed."),
    ALTATableAItem(15, None, "Rectified orthophoto",
        "Plat overlaid on rectified orthophoto if requested."),
    ALTATableAItem(16, None, "Earth-moving / additions / demolition",
        "Observed evidence of recent earth-moving work, building additions, or demolition."),
    ALTATableAItem(17, None, "Proposed changes",
        "Proposed changes to street right-of-way lines if available."),
    ALTATableAItem(18, None, "Existing utility easements",
        "Existing utility easement locations from observed evidence and provided documents."),
    ALTATableAItem(19, None, "Wetlands",
        "Wetlands delineation by qualified specialist; surveyor locates the delineated boundary."),
    ALTATableAItem(20, None, "Liability insurance",
        "Surveyor's professional liability insurance certificate provided to client."),
    ALTATableAItem(21, "a", "Mean high water / tide",
        "Tide-affected boundaries: mean high water mark located per coastal-state law."),
    ALTATableAItem(21, "b", "Coastal mark line",
        "Where applicable, coastal-construction control line located."),
)


def alta_table_a_catalog() -> tuple[ALTATableAItem, ...]:
    """Return the full canonical 2021 Table A item list."""
    return _ALTA_TABLE_A


def alta_table_a_lookup(key: str) -> ALTATableAItem:
    """Look up a Table A item by its key (e.g. "6a", "11", "21a")."""
    for item in _ALTA_TABLE_A:
        if item.key == key:
            return item
    raise KeyError(f"No ALTA Table A item with key {key!r}.")


# ── State certification language ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StatutoryTemplate:
    """A state-specific certification block.

    The :attr:`text` may contain ``{name}``, ``{license_number}``,
    ``{state_full}``, ``{date}``, ``{project_name}`` placeholders that are
    interpolated at render time.
    """

    state: str               # 2-letter code
    state_full: str          # "Texas"
    citation: str            # statute / rule that authorises this language
    text: str

    def render(self, *, surveyor: SurveyorIdentity, project: SurveyProject, issue_date: dt.date) -> str:
        return self.text.format(
            name=surveyor.name,
            license_number=surveyor.license_number,
            state_full=self.state_full,
            date=issue_date.isoformat(),
            project_name=project.project_name,
        )


_GENERIC_TEXT = (
    "I, {name}, a Professional Land Surveyor licensed in the State of "
    "{state_full} (License No. {license_number}), hereby certify that this "
    "survey was made on the ground under my direct supervision and that the "
    "survey and the resulting plat correctly represent the facts found at "
    "the time of the survey, in accordance with the laws and regulations of "
    "the State of {state_full}. Dated: {date}."
)


STATE_TEMPLATES: dict[str, StatutoryTemplate] = {
    "TX": StatutoryTemplate(
        state="TX", state_full="Texas",
        citation="22 Tex. Admin. Code § 663.16; Texas Occ. Code Ch. 1071",
        text=(
            "I, {name}, a Registered Professional Land Surveyor licensed by "
            "the Texas Board of Professional Engineers and Land Surveyors "
            "(License No. {license_number}), do hereby certify that this "
            "survey of {project_name} was performed on the ground under my "
            "direct supervision, that the survey is true and correct to the "
            "best of my knowledge and belief, and that this plat is "
            "submitted in compliance with 22 Tex. Admin. Code § 663.16. "
            "Dated this {date}."
        ),
    ),
    "FL": StatutoryTemplate(
        state="FL", state_full="Florida",
        citation="Fla. Admin. Code R. 5J-17.052; Fla. Stat. § 472",
        text=(
            "I, {name}, a Professional Surveyor and Mapper licensed by the "
            "State of {state_full} (License No. {license_number}), hereby "
            "certify that the survey shown hereon meets the Standards of "
            "Practice set forth in Chapter 5J-17, Florida Administrative "
            "Code, pursuant to Section 472, Florida Statutes. Dated: {date}."
        ),
    ),
    "CA": StatutoryTemplate(
        state="CA", state_full="California",
        citation="Cal. Bus. & Prof. Code § 8761; 16 CCR § 464",
        text=(
            "I, {name}, a Licensed Land Surveyor in the State of California "
            "(License No. {license_number}), hereby certify that this "
            "survey was made by me or under my direction in conformance "
            "with the Professional Land Surveyors' Act and the Land "
            "Surveyors Manual. Dated: {date}."
        ),
    ),
    "NY": StatutoryTemplate(
        state="NY", state_full="New York",
        citation="N.Y. Educ. Law § 7203; 8 NYCRR § 68.6",
        text=(
            "I, {name}, a Licensed Land Surveyor in the State of New York "
            "(License No. {license_number}), hereby certify that this map "
            "is the result of an actual on-the-ground survey performed by "
            "me or under my direct supervision, made in accordance with the "
            "current Code of Practice for Land Surveys adopted by the New "
            "York State Association of Professional Land Surveyors. "
            "Unauthorized alteration or addition to this survey is a "
            "violation of Section 7209 of the New York State Education Law. "
            "Dated: {date}."
        ),
    ),
    "OH": StatutoryTemplate(
        state="OH", state_full="Ohio",
        citation="Ohio Admin. Code 4733-37; Ohio Rev. Code § 4733",
        text=(
            "I, {name}, a Professional Surveyor licensed by the State of "
            "Ohio (License No. {license_number}), hereby certify that this "
            "survey was performed in accordance with the Minimum Standards "
            "for Boundary Surveys (OAC 4733-37) and that the plat correctly "
            "depicts the results thereof. Dated: {date}."
        ),
    ),
    "CO": StatutoryTemplate(
        state="CO", state_full="Colorado",
        citation="C.R.S. § 38-51; 4 CCR 730-1",
        text=(
            "I, {name}, a Professional Land Surveyor licensed in the State "
            "of Colorado (License No. {license_number}), do hereby state "
            "that this survey was made by me or under my direct "
            "responsibility, supervision, and checking, in accordance with "
            "applicable standards of practice and Title 38, Article 51 of "
            "the Colorado Revised Statutes. Dated: {date}."
        ),
    ),
    "VA": StatutoryTemplate(
        state="VA", state_full="Virginia",
        citation="18 VAC 10-20-370; Va. Code § 54.1-405",
        text=(
            "I, {name}, a Professional Land Surveyor licensed in the "
            "Commonwealth of Virginia (License No. {license_number}), "
            "certify that this plat is correct to the best of my knowledge "
            "and was prepared in accordance with the Minimum Standards for "
            "Land Boundary Surveys, 18 VAC 10-20-370. Dated: {date}."
        ),
    ),
    "GA": StatutoryTemplate(
        state="GA", state_full="Georgia",
        citation="O.C.G.A. § 15-6-67; Ga. Bd. of Land Surveyors rules",
        text=(
            "I, {name}, a Registered Professional Land Surveyor in the "
            "State of Georgia (License No. {license_number}), hereby "
            "certify that this plat is a true and correct representation of "
            "a survey made under my direct supervision and meets the "
            "minimum technical standards of O.C.G.A. § 15-6-67. "
            "Dated: {date}."
        ),
    ),
    "PA": StatutoryTemplate(
        state="PA", state_full="Pennsylvania",
        citation="49 Pa. Code § 37.51; 63 P.S. § 151",
        text=(
            "I, {name}, a Professional Land Surveyor licensed in the "
            "Commonwealth of Pennsylvania (License No. {license_number}), "
            "hereby certify that this survey and plat were prepared by me "
            "or under my direct personal supervision in accordance with 49 "
            "Pa. Code Chapter 37. Dated: {date}."
        ),
    ),
    "NC": StatutoryTemplate(
        state="NC", state_full="North Carolina",
        citation="N.C. Gen. Stat. § 47-30; 21 NCAC 56.1600",
        text=(
            "I, {name}, a Professional Land Surveyor licensed in North "
            "Carolina (License No. {license_number}), certify that this "
            "plat was drawn under my supervision from an actual survey, "
            "and that the plat conforms to the Standards of Practice for "
            "Land Surveying in North Carolina (21 NCAC 56.1600) and meets "
            "the requirements of N.C. Gen. Stat. § 47-30. Dated: {date}."
        ),
    ),
}


def get_statutory_template(state: str) -> StatutoryTemplate:
    """Return the certification template for the given state.

    States not in :data:`STATE_TEMPLATES` get a generic template with the
    state name interpolated. The result is always usable; a less specific
    template just costs the surveyor a manual edit before signing.
    """
    code = state.upper()
    if code in STATE_TEMPLATES:
        return STATE_TEMPLATES[code]
    return StatutoryTemplate(
        state=code,
        state_full=_state_full_name(code),
        citation="Generic — replace with the citation for your jurisdiction.",
        text=_GENERIC_TEXT,
    )


# ── Certificate ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Certificate:
    """A complete, ready-to-sign certificate."""

    certificate_type: CertificateType
    surveyor: SurveyorIdentity
    project: SurveyProject
    issue_date: dt.date
    statutory: StatutoryTemplate
    statutory_text_rendered: str
    additional_certifications: tuple[str, ...] = ()
    alta_items: tuple[ALTATableAItem, ...] = ()
    accuracy_class: SurveyAccuracyClass | None = None
    disclaimers: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)


def build_certificate(
    *,
    certificate_type: CertificateType,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    issue_date: dt.date | None = None,
    additional_certifications: tuple[str, ...] = (),
    alta_items: tuple[ALTATableAItem, ...] = (),
    accuracy_class: SurveyAccuracyClass | None = None,
    disclaimers: tuple[str, ...] = (),
    extra: dict[str, str] | None = None,
) -> Certificate:
    """Assemble a :class:`Certificate` for any survey type.

    Use the type-specific helpers (e.g. :func:`build_alta_certificate`) for
    the common cases — they pre-fill the right disclaimers and constraints.
    """
    issue = issue_date or dt.date.today()
    statutory = get_statutory_template(project.state)
    rendered = statutory.render(surveyor=surveyor, project=project, issue_date=issue)
    if certificate_type is CertificateType.ALTA_NSPS and not alta_items:
        # ALTA certs don't *require* Table A items, but if none were chosen the
        # surveyor should at least be aware. Don't raise; just note.
        pass
    return Certificate(
        certificate_type=certificate_type,
        surveyor=surveyor,
        project=project,
        issue_date=issue,
        statutory=statutory,
        statutory_text_rendered=rendered,
        additional_certifications=tuple(additional_certifications),
        alta_items=tuple(alta_items),
        accuracy_class=accuracy_class,
        disclaimers=tuple(disclaimers),
        extra=dict(extra or {}),
    )


def build_alta_certificate(
    *,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    table_a_keys: list[str] | tuple[str, ...] = (),
    accuracy_class: SurveyAccuracyClass = SurveyAccuracyClass.URBAN,
    issue_date: dt.date | None = None,
) -> Certificate:
    """Build an ALTA/NSPS 2021 Land Title Survey certificate.

    ``table_a_keys`` is a list of Table A item keys (e.g. ``["1", "3", "6a", "11"]``)
    that the client requested. They become the certified Table A items on the
    output certificate.
    """
    items = tuple(alta_table_a_lookup(k) for k in table_a_keys)
    extra_certs = (
        "This survey was made in accordance with the 2021 Minimum Standard "
        "Detail Requirements for ALTA/NSPS Land Title Surveys, jointly "
        "established and adopted by ALTA and NSPS, and includes Items "
        f"{', '.join(i.key for i in items) or '(none)'} of Table A thereof.",
    )
    disclaimers = (
        "The undersigned has neither abstracted the public records nor "
        "performed a title search; matters of record affecting title may "
        "exist that are not shown.",
    )
    return build_certificate(
        certificate_type=CertificateType.ALTA_NSPS,
        surveyor=surveyor,
        project=project,
        issue_date=issue_date,
        additional_certifications=extra_certs,
        alta_items=items,
        accuracy_class=accuracy_class,
        disclaimers=disclaimers,
    )


def build_boundary_certificate(
    *,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    issue_date: dt.date | None = None,
) -> Certificate:
    """Build a standard boundary-survey certificate."""
    return build_certificate(
        certificate_type=CertificateType.BOUNDARY,
        surveyor=surveyor,
        project=project,
        issue_date=issue_date,
        disclaimers=(
            "This certificate applies to the boundary depicted on the "
            "accompanying plat only. No representation is made about title, "
            "encumbrances, or matters not shown of record.",
        ),
    )


def build_mortgage_inspection_certificate(
    *,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    issue_date: dt.date | None = None,
) -> Certificate:
    """Build a (limited-liability) mortgage-inspection / mortgage-loan certificate.

    A mortgage inspection is *not* a boundary survey: corners are not
    monumented, dimensions are scaled, and the surveyor's liability is
    intentionally narrowed. The disclaimer is part of the deliverable.
    """
    return build_certificate(
        certificate_type=CertificateType.MORTGAGE_INSPECTION,
        surveyor=surveyor,
        project=project,
        issue_date=issue_date,
        disclaimers=(
            "THIS IS NOT A BOUNDARY SURVEY. This Mortgage Inspection has "
            "been prepared for the lender's use in connection with a "
            "mortgage transaction only. Property corners were not set, "
            "and dimensions are scaled from the recorded plat or deed. "
            "No reliance for boundary location, fence placement, or "
            "construction is intended or warranted.",
            "This document is not a substitute for a boundary survey and "
            "may not be used to convey title or to determine the precise "
            "location of property lines.",
        ),
    )


def build_subdivision_certificate(
    *,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    issue_date: dt.date | None = None,
) -> Certificate:
    """Build a subdivision-plat certificate."""
    return build_certificate(
        certificate_type=CertificateType.SUBDIVISION,
        surveyor=surveyor,
        project=project,
        issue_date=issue_date,
        additional_certifications=(
            "All lots and blocks shown hereon have been monumented as "
            "required by the applicable subdivision regulations of the "
            "jurisdiction having authority over this plat.",
        ),
    )


def build_elevation_certificate(
    *,
    surveyor: SurveyorIdentity,
    project: SurveyProject,
    issue_date: dt.date | None = None,
) -> Certificate:
    """Build a FEMA elevation certificate header (the rest is the FEMA form)."""
    if not project.flood_zone:
        raise ValueError(
            "Elevation certificates require project.flood_zone to be populated."
        )
    if not project.vertical_datum:
        raise ValueError(
            "Elevation certificates require project.vertical_datum to be populated."
        )
    return build_certificate(
        certificate_type=CertificateType.ELEVATION,
        surveyor=surveyor,
        project=project,
        issue_date=issue_date,
        additional_certifications=(
            f"Elevations shown hereon are referenced to {project.vertical_datum}. "
            f"FEMA flood zone designation: {project.flood_zone}.",
            "This certificate accompanies (and does not replace) FEMA Form "
            "086-0-33, the Elevation Certificate, which contains the "
            "regulatory data required for flood-insurance underwriting.",
        ),
    )


# ── Validation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str            # "error" | "warning"
    message: str


def validate_certificate(cert: Certificate) -> tuple[ValidationIssue, ...]:
    """Cross-check a certificate for surveyor / project / type consistency.

    Errors are blockers (you should not print this until fixed). Warnings are
    soft hints (e.g. the surveyor is licensed in a different state from the
    property).
    """
    issues: list[ValidationIssue] = []

    if cert.surveyor.license_state.upper() != cert.project.state.upper():
        issues.append(
            ValidationIssue(
                severity="warning",
                message=(
                    f"Surveyor is licensed in {cert.surveyor.license_state} but "
                    f"property is in {cert.project.state}; reciprocity / comity "
                    "may be required."
                ),
            )
        )

    if (
        cert.surveyor.license_expiration is not None
        and cert.surveyor.license_expiration < cert.issue_date
    ):
        issues.append(
            ValidationIssue(
                severity="error",
                message=(
                    f"Surveyor license expired on "
                    f"{cert.surveyor.license_expiration.isoformat()}, before "
                    f"the certificate issue date {cert.issue_date.isoformat()}."
                ),
            )
        )

    if (
        cert.project.field_end is not None
        and cert.project.field_end > cert.issue_date
    ):
        issues.append(
            ValidationIssue(
                severity="error",
                message=(
                    f"Field work ended on {cert.project.field_end.isoformat()}, "
                    f"after the certificate issue date {cert.issue_date.isoformat()}."
                ),
            )
        )

    if cert.certificate_type is CertificateType.ALTA_NSPS:
        if cert.accuracy_class is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message="ALTA certificate has no positional accuracy class set.",
                )
            )
    elif cert.alta_items:
        issues.append(
            ValidationIssue(
                severity="error",
                message=(
                    "ALTA Table A items are only valid on ALTA/NSPS "
                    f"certificates; got {cert.certificate_type.value}."
                ),
            )
        )

    if cert.certificate_type is CertificateType.ELEVATION and not cert.project.flood_zone:
        issues.append(
            ValidationIssue(severity="error", message="Elevation certificate is missing flood_zone.")
        )

    if cert.statutory.citation.startswith("Generic"):
        issues.append(
            ValidationIssue(
                severity="warning",
                message=(
                    f"No statutory template configured for state "
                    f"{cert.project.state.upper()}; the generic template is "
                    "in use. Replace the citation before signing."
                ),
            )
        )

    return tuple(issues)


def validate_alta_compliance(
    cert: Certificate,
    *,
    required_keys: list[str] | tuple[str, ...] = (),
) -> tuple[ValidationIssue, ...]:
    """Confirm the ALTA certificate covers the keys the client requested.

    Use case: client emailed "we need 1, 3, 4, 6a, 11" — pass that list as
    ``required_keys`` and this returns one issue per missing key.
    """
    if cert.certificate_type is not CertificateType.ALTA_NSPS:
        return (ValidationIssue(severity="error", message="Not an ALTA certificate."),)
    have = {item.key for item in cert.alta_items}
    issues: list[ValidationIssue] = []
    for k in required_keys:
        if k not in have:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"ALTA Table A item {k!r} requested by client is missing.",
                )
            )
    return tuple(issues)


# ── Rendering ───────────────────────────────────────────────────────────────


def render_text(cert: Certificate) -> str:
    """Plain-text rendering — useful for emails, RFC822 attachments, audits."""
    lines: list[str] = []
    title = _certificate_title(cert.certificate_type)
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append(f"Project:    {cert.project.project_name}")
    if cert.project.property_address:
        lines.append(f"Address:    {cert.project.property_address}")
    if cert.project.parcel_id:
        lines.append(f"Parcel ID:  {cert.project.parcel_id}")
    if cert.project.county:
        lines.append(f"County:     {cert.project.county}, {cert.project.state.upper()}")
    else:
        lines.append(f"State:      {cert.project.state.upper()}")
    lines.append(f"Survey:     {cert.project.survey_date.isoformat()}")
    if cert.project.drawing_number:
        lines.append(f"Drawing #:  {cert.project.drawing_number}")
    if cert.project.job_number:
        lines.append(f"Job #:      {cert.project.job_number}")
    if cert.project.client_name:
        lines.append(f"Client:     {cert.project.client_name}")
    if cert.accuracy_class:
        lines.append(f"Accuracy:   {cert.accuracy_class.value}")
    if cert.project.closure_ratio_text:
        lines.append(f"Closure:    {cert.project.closure_ratio_text}")
    lines.append("")
    lines.append("LEGAL DESCRIPTION")
    lines.append("-----------------")
    lines.extend(_wrap(cert.project.legal_description, 80))
    lines.append("")
    lines.append("CERTIFICATION")
    lines.append("-------------")
    lines.extend(_wrap(cert.statutory_text_rendered, 80))
    lines.append("")
    if cert.additional_certifications:
        lines.append("ADDITIONAL CERTIFICATIONS")
        lines.append("-------------------------")
        for c in cert.additional_certifications:
            lines.extend(_wrap(c, 80))
            lines.append("")
    if cert.alta_items:
        lines.append("ALTA TABLE A ITEMS")
        lines.append("------------------")
        for item in cert.alta_items:
            lines.append(f"  Item {item.key}: {item.short_label}")
            lines.extend(_wrap("    " + item.description, 80))
        lines.append("")
    if cert.disclaimers:
        lines.append("DISCLAIMERS")
        lines.append("-----------")
        for d in cert.disclaimers:
            lines.extend(_wrap(d, 80))
            lines.append("")
    lines.append(f"Statutory authority: {cert.statutory.citation}")
    lines.append("")
    lines.append("________________________________")
    lines.append(f"{cert.surveyor.name}, PLS")
    lines.append(f"{cert.surveyor.license_state.upper()} License No. {cert.surveyor.license_number}")
    if cert.surveyor.business_name:
        lines.append(cert.surveyor.business_name)
    lines.append(f"Issued: {cert.issue_date.isoformat()}")
    return "\n".join(lines)


def render_html(cert: Certificate) -> str:
    """Print-ready HTML rendering with embedded CSS (no external assets).

    The page is laid out for US Letter; print directly from a browser to PDF
    (or pipe through a headless renderer) to obtain a sealable copy.
    """
    title = _certificate_title(cert.certificate_type)
    parts: list[str] = [
        '<!DOCTYPE html>',
        '<html lang="en"><head>',
        '<meta charset="utf-8">',
        f'<title>{html.escape(title)} — {html.escape(cert.project.project_name)}</title>',
        "<style>",
        _CERT_CSS,
        "</style>",
        "</head><body>",
        '<main class="cert">',
        f'<h1>{html.escape(title)}</h1>',
        '<dl class="meta">',
        f"<dt>Project</dt><dd>{html.escape(cert.project.project_name)}</dd>",
    ]
    if cert.project.property_address:
        parts.append(f"<dt>Address</dt><dd>{html.escape(cert.project.property_address)}</dd>")
    if cert.project.parcel_id:
        parts.append(f"<dt>Parcel&nbsp;ID</dt><dd>{html.escape(cert.project.parcel_id)}</dd>")
    where = f"{cert.project.county + ', ' if cert.project.county else ''}{cert.project.state.upper()}"
    parts.append(f"<dt>Jurisdiction</dt><dd>{html.escape(where)}</dd>")
    parts.append(f"<dt>Survey&nbsp;date</dt><dd>{cert.project.survey_date.isoformat()}</dd>")
    if cert.project.drawing_number:
        parts.append(f"<dt>Drawing&nbsp;#</dt><dd>{html.escape(cert.project.drawing_number)}</dd>")
    if cert.project.job_number:
        parts.append(f"<dt>Job&nbsp;#</dt><dd>{html.escape(cert.project.job_number)}</dd>")
    if cert.project.client_name:
        parts.append(f"<dt>Client</dt><dd>{html.escape(cert.project.client_name)}</dd>")
    if cert.accuracy_class:
        parts.append(f"<dt>Accuracy</dt><dd>{cert.accuracy_class.value.title()}</dd>")
    if cert.project.closure_ratio_text:
        parts.append(f"<dt>Closure</dt><dd>{html.escape(cert.project.closure_ratio_text)}</dd>")
    parts.append("</dl>")

    parts.append('<section class="legal"><h2>Legal description</h2>')
    parts.append(f"<p>{html.escape(cert.project.legal_description)}</p></section>")

    parts.append('<section class="certification"><h2>Certification</h2>')
    parts.append(f"<p>{html.escape(cert.statutory_text_rendered)}</p>")
    for line in cert.additional_certifications:
        parts.append(f"<p>{html.escape(line)}</p>")
    parts.append("</section>")

    if cert.alta_items:
        parts.append('<section class="alta"><h2>ALTA/NSPS Table A items certified</h2><ul>')
        for item in cert.alta_items:
            parts.append(
                f'<li><strong>Item {html.escape(item.key)}.</strong> '
                f"{html.escape(item.short_label)} — {html.escape(item.description)}</li>"
            )
        parts.append("</ul></section>")

    if cert.disclaimers:
        parts.append('<section class="disclaimers"><h2>Disclaimers</h2>')
        for d in cert.disclaimers:
            parts.append(f"<p>{html.escape(d)}</p>")
        parts.append("</section>")

    parts.append(
        '<footer>'
        f'<p class="citation">Statutory authority: {html.escape(cert.statutory.citation)}</p>'
        '<div class="signature-block">'
        '<div class="line"></div>'
        f'<p class="surveyor">{html.escape(cert.surveyor.name)}, PLS<br>'
        f"{cert.surveyor.license_state.upper()} License No. "
        f"{html.escape(cert.surveyor.license_number)}"
        + (f"<br>{html.escape(cert.surveyor.business_name)}" if cert.surveyor.business_name else "")
        + f"</p>"
        f'<p class="issued">Issued: {cert.issue_date.isoformat()}</p>'
        '<div class="seal-placeholder">[ Surveyor\'s Seal ]</div>'
        '</div></footer>'
        "</main></body></html>"
    )
    return "\n".join(parts)


_CERT_CSS = """
@page { size: letter; margin: 0.75in; }
body { font-family: Georgia, "Times New Roman", serif; color: #111; line-height: 1.45; margin: 0; }
.cert { max-width: 7in; margin: 0.5in auto; padding: 0 0.25in; }
h1 { font-size: 22pt; text-align: center; margin: 0 0 6pt 0; letter-spacing: 0.05em; }
h2 { font-size: 13pt; margin: 18pt 0 6pt 0; border-bottom: 1pt solid #444; padding-bottom: 2pt; }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: 2pt 12pt; margin: 0 0 12pt 0; font-size: 11pt; }
dl.meta dt { font-weight: 600; color: #555; }
dl.meta dd { margin: 0; }
section.legal p, section.certification p, section.disclaimers p { font-size: 11pt; text-align: justify; }
section.alta ul { font-size: 10.5pt; margin: 0; padding-left: 1.2em; }
section.alta li { margin-bottom: 4pt; }
footer { margin-top: 24pt; }
footer p.citation { font-size: 9pt; color: #555; font-style: italic; margin-bottom: 18pt; }
.signature-block .line { border-top: 1pt solid #111; width: 3.5in; margin-top: 36pt; }
.signature-block p.surveyor { font-size: 11pt; margin: 4pt 0; }
.signature-block p.issued { font-size: 10pt; color: #444; }
.signature-block .seal-placeholder {
  margin-top: 12pt; width: 1.5in; height: 1.5in;
  border: 1pt dashed #888; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 9pt; color: #888;
}
"""


# ── Helpers ─────────────────────────────────────────────────────────────────


def _certificate_title(t: CertificateType) -> str:
    return {
        CertificateType.BOUNDARY: "Boundary Survey Certificate",
        CertificateType.ALTA_NSPS: "ALTA/NSPS Land Title Survey Certificate",
        CertificateType.MORTGAGE_INSPECTION: "Mortgage Inspection Certificate",
        CertificateType.TOPOGRAPHIC: "Topographic Survey Certificate",
        CertificateType.AS_BUILT: "As-Built Survey Certificate",
        CertificateType.SUBDIVISION: "Subdivision Plat Certificate",
        CertificateType.ELEVATION: "Elevation Certificate",
        CertificateType.LOT_SURVEY: "Lot Survey Certificate",
        CertificateType.ROUTE: "Route Survey Certificate",
        CertificateType.CONSTRUCTION_STAKING: "Construction Staking Certificate",
    }[t]


def _wrap(text: str, width: int) -> list[str]:
    """Word-wrap a paragraph to ``width`` columns. Preserves paragraph breaks."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        line = words[0]
        for w in words[1:]:
            if len(line) + 1 + len(w) <= width:
                line += " " + w
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _state_full_name(code: str) -> str:
    return _STATE_NAMES.get(code.upper(), code.upper())


__all__ = [
    "ALTATableAItem",
    "Certificate",
    "CertificateType",
    "SealType",
    "StatutoryTemplate",
    "SurveyAccuracyClass",
    "SurveyProject",
    "SurveyorIdentity",
    "ValidationIssue",
    "alta_table_a_catalog",
    "alta_table_a_lookup",
    "build_alta_certificate",
    "build_boundary_certificate",
    "build_certificate",
    "build_elevation_certificate",
    "build_mortgage_inspection_certificate",
    "build_subdivision_certificate",
    "get_statutory_template",
    "render_html",
    "render_text",
    "validate_alta_compliance",
    "validate_certificate",
]
