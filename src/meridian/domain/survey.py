"""Survey and SurveyProject — the top-level aggregates.

A :class:`SurveyProject` is the unit of *work* a surveyor opens, edits,
and saves. It contains one or more :class:`Survey` objects, which each
hold the geometry, observations, parcels, deeds, and surfaces for a
single conceptual scope (e.g. "front 40", "subdivision phase 2").

These are mutable on purpose: they are aggregate roots that accumulate
changes as the user works. The dataclass uses ``field(default_factory=...)``
to produce fresh containers per instance — never share these between
projects.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.crs import CRS
    from meridian.domain.deed import Deed
    from meridian.domain.network import ControlNetwork, NetworkAdjustment
    from meridian.domain.observation import Setup
    from meridian.domain.parcel import Parcel
    from meridian.domain.pointcloud import PointCloud, Surface


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(slots=True)
class Survey:
    """A single coherent body of survey data.

    Holds: control network, parcels, point clouds, derived surfaces, deeds.
    The CRS at the survey level is the *working CRS* — coordinates of all
    contained entities should be in this CRS unless explicitly stated.
    """

    name: str
    crs: CRS
    id: str = field(default_factory=_new_id)
    description: str | None = None

    setups: list[Setup] = field(default_factory=list)
    networks: list[ControlNetwork] = field(default_factory=list)
    adjustments: list[NetworkAdjustment] = field(default_factory=list)
    parcels: list[Parcel] = field(default_factory=list)
    deeds: list[Deed] = field(default_factory=list)
    point_clouds: list[PointCloud] = field(default_factory=list)
    surfaces: list[Surface] = field(default_factory=list)

    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = field(default_factory=dt.datetime.utcnow)

    def touch(self) -> None:
        """Mark the survey modified."""
        self.updated_at = dt.datetime.utcnow()


@dataclass(slots=True)
class SurveyProject:
    """The top-level aggregate the user opens and saves.

    Holds one or more :class:`Survey` objects (most projects have one,
    but multi-phase / multi-tract projects can hold several). Project
    metadata — surveyor of record, client, license info — lives here.
    """

    name: str
    id: str = field(default_factory=_new_id)
    description: str | None = None
    surveys: list[Survey] = field(default_factory=list)

    # Project-level metadata
    surveyor_of_record: str | None = None
    license_state: str | None = None
    license_number: str | None = None
    client: str | None = None
    job_number: str | None = None
    location: str | None = None        # county, state, township-range, etc.
    keywords: tuple[str, ...] = ()

    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = field(default_factory=dt.datetime.utcnow)

    def touch(self) -> None:
        self.updated_at = dt.datetime.utcnow()

    def add_survey(self, survey: Survey) -> Survey:
        self.surveys.append(survey)
        self.touch()
        return survey

    def get_survey(self, name: str) -> Survey | None:
        for s in self.surveys:
            if s.name == name:
                return s
        return None
