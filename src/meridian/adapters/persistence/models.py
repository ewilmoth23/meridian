"""SQLAlchemy ORM models — single canonical persistence schema.

Replaces the prototype's seven orphan SQLite databases with one schema,
one set of foreign keys, one Alembic migration history. The mapping
from domain entities to ORM rows is intentionally explicit (no
auto-discovery): the ORM models live here, and the
``adapters.persistence.repositories`` module translates between them and
``meridian.domain.*`` entities.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common base class for all Meridian ORM models."""

    type_annotation_map: dict[Any, Any] = {dict[str, Any]: JSON}


# ── Project / survey ────────────────────────────────────────────────────────


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    surveyor_of_record: Mapped[str | None] = mapped_column(String(256), default=None)
    license_state: Mapped[str | None] = mapped_column(String(8), default=None)
    license_number: Mapped[str | None] = mapped_column(String(64), default=None)
    client: Mapped[str | None] = mapped_column(String(256), default=None)
    job_number: Mapped[str | None] = mapped_column(String(64), default=None)
    location: Mapped[str | None] = mapped_column(String(256), default=None)
    keywords: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    surveys: Mapped[list[SurveyModel]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SurveyModel(Base):
    __tablename__ = "surveys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    crs_epsg: Mapped[int | None] = mapped_column(Integer(), default=None)
    crs_wkt: Mapped[str | None] = mapped_column(Text(), default=None)
    crs_extra: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    project: Mapped[ProjectModel] = relationship(back_populates="surveys")
    parcels: Mapped[list[ParcelModel]] = relationship(back_populates="survey", cascade="all, delete-orphan")
    point_clouds: Mapped[list[PointCloudModel]] = relationship(back_populates="survey", cascade="all, delete-orphan")
    networks: Mapped[list[ControlNetworkModel]] = relationship(back_populates="survey", cascade="all, delete-orphan")


# ── Parcel / call ───────────────────────────────────────────────────────────


class ParcelModel(Base):
    __tablename__ = "parcels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    survey_id: Mapped[str] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    apn: Mapped[str | None] = mapped_column(String(64), default=None)
    legal_description: Mapped[str | None] = mapped_column(Text(), default=None)
    grantor: Mapped[str | None] = mapped_column(String(256), default=None)
    grantee: Mapped[str | None] = mapped_column(String(256), default=None)
    recorded_date: Mapped[dt.date | None] = mapped_column(default=None)
    recording: Mapped[str | None] = mapped_column(String(128), default=None)
    acreage: Mapped[float | None] = mapped_column(Float(), default=None)
    address: Mapped[str | None] = mapped_column(String(512), default=None)
    boundary_wkt: Mapped[str | None] = mapped_column(Text(), default=None)
    perimeter_m: Mapped[float | None] = mapped_column(Float(), default=None)
    misclosure_m: Mapped[float | None] = mapped_column(Float(), default=None)
    closure_ratio: Mapped[float | None] = mapped_column(Float(), default=None)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)

    survey: Mapped[SurveyModel] = relationship(back_populates="parcels")
    calls: Mapped[list[CallModel]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan", order_by="CallModel.raw_index"
    )


class CallModel(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer(), primary_key=True, autoincrement=True)
    parcel_id: Mapped[str] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"))
    raw_index: Mapped[int] = mapped_column(Integer())
    kind: Mapped[str] = mapped_column(String(32))
    bearing_rad: Mapped[float | None] = mapped_column(Float(), default=None)
    distance_m: Mapped[float | None] = mapped_column(Float(), default=None)
    radius_m: Mapped[float | None] = mapped_column(Float(), default=None)
    delta_rad: Mapped[float | None] = mapped_column(Float(), default=None)
    chord_m: Mapped[float | None] = mapped_column(Float(), default=None)
    clockwise: Mapped[bool | None] = mapped_column(default=None)
    monument: Mapped[str | None] = mapped_column(String(256), default=None)
    notes: Mapped[str | None] = mapped_column(Text(), default=None)

    parcel: Mapped[ParcelModel] = relationship(back_populates="calls")


# ── Control network ─────────────────────────────────────────────────────────


class ControlNetworkModel(Base):
    __tablename__ = "control_networks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    survey_id: Mapped[str] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    constraint_mode: Mapped[str] = mapped_column(String(16))

    survey: Mapped[SurveyModel] = relationship(back_populates="networks")
    points: Mapped[list[ControlPointModel]] = relationship(
        back_populates="network", cascade="all, delete-orphan"
    )
    observations: Mapped[list[ObservationModel]] = relationship(
        back_populates="network", cascade="all, delete-orphan"
    )


class ControlPointModel(Base):
    __tablename__ = "control_points"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("control_networks.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    x: Mapped[float] = mapped_column(Float())
    y: Mapped[float] = mapped_column(Float())
    z: Mapped[float] = mapped_column(Float())
    fixed: Mapped[bool] = mapped_column(default=False)
    monument: Mapped[str] = mapped_column(String(32), default="undefined")
    sigma_x: Mapped[float | None] = mapped_column(Float(), default=None)
    sigma_y: Mapped[float | None] = mapped_column(Float(), default=None)
    sigma_z: Mapped[float | None] = mapped_column(Float(), default=None)
    code: Mapped[str | None] = mapped_column(String(32), default=None)

    network: Mapped[ControlNetworkModel] = relationship(back_populates="points")


class ObservationModel(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer(), primary_key=True, autoincrement=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("control_networks.id", ondelete="CASCADE"))
    obs_id: Mapped[str] = mapped_column(String(64))
    setup_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    from_point: Mapped[str] = mapped_column(String(64))
    to_point: Mapped[str | None] = mapped_column(String(64), default=None)
    value: Mapped[float | None] = mapped_column(Float(), default=None)
    vector_x: Mapped[float | None] = mapped_column(Float(), default=None)
    vector_y: Mapped[float | None] = mapped_column(Float(), default=None)
    vector_z: Mapped[float | None] = mapped_column(Float(), default=None)
    sigma: Mapped[float | None] = mapped_column(Float(), default=None)
    target_height: Mapped[float | None] = mapped_column(Float(), default=None)
    rejected: Mapped[bool] = mapped_column(default=False)

    network: Mapped[ControlNetworkModel] = relationship(back_populates="observations")


# ── Point clouds ────────────────────────────────────────────────────────────


class PointCloudModel(Base):
    __tablename__ = "point_clouds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    survey_id: Mapped[str] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(Text())
    crs_epsg: Mapped[int | None] = mapped_column(Integer(), default=None)
    crs_wkt: Mapped[str | None] = mapped_column(Text(), default=None)
    point_count: Mapped[int | None] = mapped_column(Integer(), default=None)
    is_copc: Mapped[bool] = mapped_column(default=False)
    bbox_min_x: Mapped[float | None] = mapped_column(Float(), default=None)
    bbox_min_y: Mapped[float | None] = mapped_column(Float(), default=None)
    bbox_min_z: Mapped[float | None] = mapped_column(Float(), default=None)
    bbox_max_x: Mapped[float | None] = mapped_column(Float(), default=None)
    bbox_max_y: Mapped[float | None] = mapped_column(Float(), default=None)
    bbox_max_z: Mapped[float | None] = mapped_column(Float(), default=None)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)

    survey: Mapped[SurveyModel] = relationship(back_populates="point_clouds")
