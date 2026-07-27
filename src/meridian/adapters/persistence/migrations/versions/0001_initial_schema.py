"""Initial Meridian schema.

Revision ID: 0001
Revises:
Create Date: 2026-05-02

Creates the complete v0.1 schema in a single migration. Subsequent
migrations will add tables incrementally and never drop columns
without an explicit data-migration plan.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("surveyor_of_record", sa.String(256)),
        sa.Column("license_state", sa.String(8)),
        sa.Column("license_number", sa.String(64)),
        sa.Column("client", sa.String(256)),
        sa.Column("job_number", sa.String(64)),
        sa.Column("location", sa.String(256)),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "surveys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("crs_epsg", sa.Integer()),
        sa.Column("crs_wkt", sa.Text()),
        sa.Column("crs_extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_surveys_project", "surveys", ["project_id"])

    op.create_table(
        "parcels",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("survey_id", sa.String(32), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("apn", sa.String(64)),
        sa.Column("legal_description", sa.Text()),
        sa.Column("grantor", sa.String(256)),
        sa.Column("grantee", sa.String(256)),
        sa.Column("recorded_date", sa.Date()),
        sa.Column("recording", sa.String(128)),
        sa.Column("acreage", sa.Float()),
        sa.Column("address", sa.String(512)),
        sa.Column("boundary_wkt", sa.Text()),
        sa.Column("perimeter_m", sa.Float()),
        sa.Column("misclosure_m", sa.Float()),
        sa.Column("closure_ratio", sa.Float()),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_parcels_survey", "parcels", ["survey_id"])

    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parcel_id", sa.String(32), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("bearing_rad", sa.Float()),
        sa.Column("distance_m", sa.Float()),
        sa.Column("radius_m", sa.Float()),
        sa.Column("delta_rad", sa.Float()),
        sa.Column("chord_m", sa.Float()),
        sa.Column("clockwise", sa.Boolean()),
        sa.Column("monument", sa.String(256)),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_calls_parcel", "calls", ["parcel_id"])

    op.create_table(
        "control_networks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("survey_id", sa.String(32), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("constraint_mode", sa.String(16), nullable=False),
    )
    op.create_index("ix_networks_survey", "control_networks", ["survey_id"])

    op.create_table(
        "control_points",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("network_id", sa.String(32), sa.ForeignKey("control_networks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("z", sa.Float(), nullable=False),
        sa.Column("fixed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("monument", sa.String(32), nullable=False, server_default="undefined"),
        sa.Column("sigma_x", sa.Float()),
        sa.Column("sigma_y", sa.Float()),
        sa.Column("sigma_z", sa.Float()),
        sa.Column("code", sa.String(32)),
    )
    op.create_index("ix_control_points_network", "control_points", ["network_id"])

    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("network_id", sa.String(32), sa.ForeignKey("control_networks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("obs_id", sa.String(64), nullable=False),
        sa.Column("setup_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("from_point", sa.String(64), nullable=False),
        sa.Column("to_point", sa.String(64)),
        sa.Column("value", sa.Float()),
        sa.Column("vector_x", sa.Float()),
        sa.Column("vector_y", sa.Float()),
        sa.Column("vector_z", sa.Float()),
        sa.Column("sigma", sa.Float()),
        sa.Column("target_height", sa.Float()),
        sa.Column("rejected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_observations_network", "observations", ["network_id"])

    op.create_table(
        "point_clouds",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("survey_id", sa.String(32), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("crs_epsg", sa.Integer()),
        sa.Column("crs_wkt", sa.Text()),
        sa.Column("point_count", sa.Integer()),
        sa.Column("is_copc", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("bbox_min_x", sa.Float()),
        sa.Column("bbox_min_y", sa.Float()),
        sa.Column("bbox_min_z", sa.Float()),
        sa.Column("bbox_max_x", sa.Float()),
        sa.Column("bbox_max_y", sa.Float()),
        sa.Column("bbox_max_z", sa.Float()),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_point_clouds_survey", "point_clouds", ["survey_id"])


def downgrade() -> None:
    op.drop_index("ix_point_clouds_survey", "point_clouds")
    op.drop_table("point_clouds")
    op.drop_index("ix_observations_network", "observations")
    op.drop_table("observations")
    op.drop_index("ix_control_points_network", "control_points")
    op.drop_table("control_points")
    op.drop_index("ix_networks_survey", "control_networks")
    op.drop_table("control_networks")
    op.drop_index("ix_calls_parcel", "calls")
    op.drop_table("calls")
    op.drop_index("ix_parcels_survey", "parcels")
    op.drop_table("parcels")
    op.drop_index("ix_surveys_project", "surveys")
    op.drop_table("surveys")
    op.drop_table("projects")
