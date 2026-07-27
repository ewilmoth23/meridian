"""Concrete repository implementations.

Translates between :mod:`meridian.domain` entities and SQLAlchemy ORM
rows. Services depend on the abstract ports in
:mod:`meridian.ports.repository`; this module supplies the concrete
SQLAlchemy-backed implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from meridian.adapters.persistence.models import (
    CallModel,
    ParcelModel,
    PointCloudModel,
    ProjectModel,
    SurveyModel,
)
from meridian.domain.crs import CRS
from meridian.domain.parcel import Call, CallKind, Parcel, ParcelMetadata
from meridian.domain.survey import Survey, SurveyProject
from meridian.ports.repository import (
    ParcelRepository,
    PointCloudRepository,
    SurveyRepository,
)

if TYPE_CHECKING:
    from meridian.domain.pointcloud import PointCloud


# ── helpers ─────────────────────────────────────────────────────────────────


def _crs_from_row(epsg: int | None, wkt: str | None) -> CRS | None:
    if epsg is not None or wkt is not None:
        return CRS(epsg=epsg, wkt=wkt)
    return None


# ── Survey / Project repository ─────────────────────────────────────────────


class SQLSurveyRepository(SurveyRepository):
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def get_project(self, project_id: str) -> SurveyProject | None:
        with self._sf() as s:
            row = s.get(ProjectModel, project_id)
            return _project_from_row(row, s) if row else None

    def list_projects(self) -> Iterable[SurveyProject]:
        with self._sf() as s:
            rows = s.query(ProjectModel).all()
            return [_project_from_row(r, s) for r in rows]

    def save_project(self, project: SurveyProject) -> str:
        with self._sf() as s:
            row = s.get(ProjectModel, project.id) or ProjectModel(id=project.id)
            row.name = project.name
            row.description = project.description
            row.surveyor_of_record = project.surveyor_of_record
            row.license_state = project.license_state
            row.license_number = project.license_number
            row.client = project.client
            row.job_number = project.job_number
            row.location = project.location
            row.keywords = list(project.keywords)
            row.updated_at = project.updated_at
            s.merge(row)
            for survey in project.surveys:
                _save_survey_orm(s, project.id, survey)
            s.commit()
        return project.id

    def delete_project(self, project_id: str) -> None:
        with self._sf() as s:
            row = s.get(ProjectModel, project_id)
            if row:
                s.delete(row)
                s.commit()

    def save_survey(self, project_id: str, survey: Survey) -> str:
        with self._sf() as s:
            _save_survey_orm(s, project_id, survey)
            s.commit()
        return survey.id


def _save_survey_orm(s: Session, project_id: str, survey: Survey) -> None:
    row = s.get(SurveyModel, survey.id) or SurveyModel(id=survey.id, project_id=project_id)
    row.project_id = project_id
    row.name = survey.name
    row.description = survey.description
    row.crs_epsg = survey.crs.epsg
    row.crs_wkt = survey.crs.wkt
    row.crs_extra = dict(survey.crs.extra)
    row.updated_at = survey.updated_at
    s.merge(row)
    for parcel in survey.parcels:
        _save_parcel_orm(s, survey.id, parcel)


def _save_parcel_orm(s: Session, survey_id: str, parcel: Parcel) -> None:
    row = s.query(ParcelModel).filter(ParcelModel.name == parcel.name, ParcelModel.survey_id == survey_id).one_or_none()
    if row is None:
        from uuid import uuid4
        row = ParcelModel(id=uuid4().hex[:12], survey_id=survey_id)
    row.name = parcel.name
    row.apn = parcel.metadata.apn
    row.legal_description = parcel.metadata.legal_description_text
    row.grantor = parcel.metadata.grantor
    row.grantee = parcel.metadata.grantee
    row.recorded_date = parcel.metadata.recorded_date
    row.recording = parcel.metadata.recording
    row.acreage = parcel.metadata.acreage
    row.address = parcel.metadata.address
    row.extra = dict(parcel.metadata.extra)
    if parcel.boundary is not None:
        row.boundary_wkt = _polygon_to_wkt(parcel.boundary.polygon)
        row.perimeter_m = parcel.boundary.perimeter
        row.misclosure_m = parcel.boundary.misclosure_distance
        row.closure_ratio = (
            parcel.boundary.closure_ratio if parcel.boundary.closure_ratio != float("inf") else None
        )
    s.merge(row)
    s.query(CallModel).filter(CallModel.parcel_id == row.id).delete()
    for call in parcel.calls:
        s.add(
            CallModel(
                parcel_id=row.id,
                raw_index=call.raw_index or 0,
                kind=call.kind.value,
                bearing_rad=call.bearing,
                distance_m=call.distance,
                radius_m=call.radius,
                delta_rad=call.delta,
                chord_m=call.chord,
                clockwise=call.clockwise,
                monument=call.monument,
                notes=call.notes,
            )
        )


def _polygon_to_wkt(polygon) -> str:
    coords = ", ".join(f"{p.x} {p.y}" for p in polygon.exterior)
    return f"POLYGON(({coords}))"


def _project_from_row(row: ProjectModel, s: Session) -> SurveyProject:
    project = SurveyProject(
        id=row.id,
        name=row.name,
        description=row.description,
        surveyor_of_record=row.surveyor_of_record,
        license_state=row.license_state,
        license_number=row.license_number,
        client=row.client,
        job_number=row.job_number,
        location=row.location,
        keywords=tuple(row.keywords or ()),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    for srow in row.surveys:
        crs = _crs_from_row(srow.crs_epsg, srow.crs_wkt)
        if crs is None:
            continue
        survey = Survey(
            id=srow.id,
            name=srow.name,
            description=srow.description,
            crs=crs,
            created_at=srow.created_at,
            updated_at=srow.updated_at,
        )
        for prow in srow.parcels:
            survey.parcels.append(_parcel_from_row(prow, crs))
        project.surveys.append(survey)
    return project


def _parcel_from_row(row: ParcelModel, crs: CRS) -> Parcel:
    metadata = ParcelMetadata(
        apn=row.apn,
        legal_description_text=row.legal_description,
        recording=row.recording,
        recorded_date=row.recorded_date,
        grantor=row.grantor,
        grantee=row.grantee,
        acreage=row.acreage,
        address=row.address,
        extra=dict(row.extra or {}),
    )
    calls = tuple(
        Call(
            kind=CallKind(c.kind),
            bearing=c.bearing_rad,
            distance=c.distance_m,
            radius=c.radius_m,
            delta=c.delta_rad,
            chord=c.chord_m,
            clockwise=c.clockwise,
            monument=c.monument,
            notes=c.notes,
            raw_index=c.raw_index,
        )
        for c in sorted(row.calls, key=lambda x: x.raw_index)
    )
    return Parcel(name=row.name, crs=crs, calls=calls, boundary=None, metadata=metadata)


# ── Parcel repository ──────────────────────────────────────────────────────


class SQLParcelRepository(ParcelRepository):
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def get(self, parcel_id: str) -> Parcel | None:
        with self._sf() as s:
            row = s.get(ParcelModel, parcel_id)
            if row is None:
                return None
            crs = _crs_from_row(row.survey.crs_epsg, row.survey.crs_wkt)
            return _parcel_from_row(row, crs) if crs else None

    def save(self, survey_id: str, parcel: Parcel) -> str:
        with self._sf() as s:
            _save_parcel_orm(s, survey_id, parcel)
            s.commit()
        return parcel.name

    def list_for_survey(self, survey_id: str) -> Iterable[Parcel]:
        with self._sf() as s:
            rows = s.query(ParcelModel).filter(ParcelModel.survey_id == survey_id).all()
            crs_row = s.get(SurveyModel, survey_id)
            if crs_row is None:
                return []
            crs = _crs_from_row(crs_row.crs_epsg, crs_row.crs_wkt)
            if crs is None:
                return []
            return [_parcel_from_row(r, crs) for r in rows]


# ── Point cloud repository ─────────────────────────────────────────────────


class SQLPointCloudRepository(PointCloudRepository):
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def register(self, survey_id: str, cloud: PointCloud) -> str:
        from uuid import uuid4
        with self._sf() as s:
            row = PointCloudModel(
                id=uuid4().hex[:12],
                survey_id=survey_id,
                name=cloud.label(),
                path=str(cloud.path),
                crs_epsg=cloud.crs.epsg,
                crs_wkt=cloud.crs.wkt,
                point_count=cloud.stats.point_count if cloud.stats else None,
                is_copc=cloud.is_copc,
                bbox_min_x=cloud.stats.bbox.min_x if cloud.stats else None,
                bbox_min_y=cloud.stats.bbox.min_y if cloud.stats else None,
                bbox_min_z=cloud.stats.bbox.min_z if cloud.stats else None,
                bbox_max_x=cloud.stats.bbox.max_x if cloud.stats else None,
                bbox_max_y=cloud.stats.bbox.max_y if cloud.stats else None,
                bbox_max_z=cloud.stats.bbox.max_z if cloud.stats else None,
                extra={
                    "classification_histogram": cloud.stats.classification_histogram if cloud.stats else {},
                },
            )
            s.add(row)
            s.commit()
            return row.id

    def list_for_survey(self, survey_id: str):
        from meridian.domain.pointcloud import PointCloud

        with self._sf() as s:
            rows = s.query(PointCloudModel).filter(PointCloudModel.survey_id == survey_id).all()
            results: list[PointCloud] = []
            for r in rows:
                crs = _crs_from_row(r.crs_epsg, r.crs_wkt)
                if crs is None:
                    continue
                from pathlib import Path
                results.append(
                    PointCloud(
                        path=Path(r.path),
                        crs=crs,
                        stats=None,
                        name=r.name,
                        is_copc=r.is_copc,
                    )
                )
            return results
