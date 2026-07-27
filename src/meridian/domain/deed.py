"""Deed document entities.

These represent the *legal document* — its parties, recordings,
encumbrances, and chain-of-title links. The geometric content lives in
:mod:`meridian.domain.parcel`. A :class:`Deed` and a :class:`Parcel` are
linked by id; one deed can describe multiple parcels (multi-tract deeds)
and one parcel can be touched by many deeds (chain of title).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum


class PartyRole(str, Enum):
    GRANTOR = "grantor"
    GRANTEE = "grantee"
    TRUSTEE = "trustee"
    BENEFICIARY = "beneficiary"
    LIENHOLDER = "lienholder"
    NOTARY = "notary"
    WITNESS = "witness"


class DeedKind(str, Enum):
    WARRANTY = "warranty"
    QUITCLAIM = "quitclaim"
    SPECIAL_WARRANTY = "special_warranty"
    GRANT = "grant"
    BARGAIN_AND_SALE = "bargain_and_sale"
    GIFT = "gift"
    TRUSTEE = "trustee"
    SHERIFF = "sheriff"
    TAX = "tax"
    PATENT = "patent"
    UNKNOWN = "unknown"


class EncumbranceKind(str, Enum):
    EASEMENT = "easement"
    LIEN = "lien"
    MORTGAGE = "mortgage"
    LEASE = "lease"
    COVENANT = "covenant"
    RESTRICTION = "restriction"
    LIFE_ESTATE = "life_estate"
    MINERAL_RESERVATION = "mineral_reservation"
    WATER_RIGHT = "water_right"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Party:
    """A person or entity referenced in a deed."""

    name: str
    role: PartyRole
    is_entity: bool = False     # True for corporations, trusts, partnerships
    address: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class Recording:
    """The county-clerk recording reference for an instrument."""

    jurisdiction: str           # "Travis County, TX" or similar
    book: str | None = None
    page: str | None = None
    instrument_number: str | None = None
    recorded_date: dt.date | None = None
    document_kind: str | None = None       # "Deed", "Mortgage", "Affidavit"
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Encumbrance:
    """A burden on the title — easement, lien, mortgage, restriction."""

    kind: EncumbranceKind
    description: str
    held_by: str | None = None       # the holder of the right
    recording: Recording | None = None
    granted_on: dt.date | None = None
    released: bool = False
    release_recording: Recording | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Deed:
    """A deed document.

    The deed's geometric description (metes and bounds) lives on the
    :class:`meridian.domain.parcel.Parcel` records linked via
    :attr:`parcel_ids`. One deed can describe multiple parcels.
    """

    id: str
    kind: DeedKind
    parties: tuple[Party, ...]
    recording: Recording
    parcel_ids: tuple[str, ...] = ()
    encumbrances: tuple[Encumbrance, ...] = ()
    consideration: str | None = None         # "$10 and other valuable consideration"
    legal_description_raw: str | None = None
    notes: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One link in a chain of title: the connection between two deeds."""

    from_deed_id: str
    to_deed_id: str
    grantor: str
    grantee: str
    transfer_date: dt.date | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ChainOfTitle:
    """A chain of title for a parcel — ordered links from earliest to latest."""

    parcel_id: str
    links: tuple[ChainLink, ...]
    defects: tuple[str, ...] = ()    # human-readable issues found by the analyzer
