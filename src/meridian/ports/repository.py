"""Repository ports.

The persistence boundary. Services and pipelines depend on these
abstractions; the SQLAlchemy-backed implementations live in
:mod:`meridian.adapters.persistence.repositories`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.domain.deed import Deed
    from meridian.domain.parcel import Parcel
    from meridian.domain.pointcloud import PointCloud
    from meridian.domain.survey import Survey, SurveyProject


class SurveyRepository(ABC):
    @abstractmethod
    def get_project(self, project_id: str) -> SurveyProject | None:
        ...

    @abstractmethod
    def list_projects(self) -> Iterable[SurveyProject]:
        ...

    @abstractmethod
    def save_project(self, project: SurveyProject) -> str:
        ...

    @abstractmethod
    def delete_project(self, project_id: str) -> None:
        ...

    @abstractmethod
    def save_survey(self, project_id: str, survey: Survey) -> str:
        ...


class ParcelRepository(ABC):
    @abstractmethod
    def get(self, parcel_id: str) -> Parcel | None:
        ...

    @abstractmethod
    def save(self, survey_id: str, parcel: Parcel) -> str:
        ...

    @abstractmethod
    def list_for_survey(self, survey_id: str) -> Iterable[Parcel]:
        ...


class DeedRepository(ABC):
    @abstractmethod
    def get(self, deed_id: str) -> Deed | None:
        ...

    @abstractmethod
    def save(self, deed: Deed) -> str:
        ...

    @abstractmethod
    def list_for_parcel(self, parcel_id: str) -> Iterable[Deed]:
        ...


class PointCloudRepository(ABC):
    @abstractmethod
    def register(self, survey_id: str, cloud: PointCloud) -> str:
        ...

    @abstractmethod
    def list_for_survey(self, survey_id: str) -> Iterable[PointCloud]:
        ...
