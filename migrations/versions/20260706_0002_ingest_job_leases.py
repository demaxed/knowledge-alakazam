"""add ingest job lease metadata

Revision ID: 20260706_0002
Revises: 20260705_0001
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_0002"
down_revision: str | None = "20260705_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_job",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "ingest_job",
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "ingest_job",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ingest_job",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("ingest_job", sa.Column("locked_by", sa.Text(), nullable=True))
    op.add_column(
        "ingest_job",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_ingest_job_attempt_count_non_negative",
        "ingest_job",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_ingest_job_max_attempts_positive",
        "ingest_job",
        "max_attempts >= 1",
    )
    op.create_index(
        "ix_ingest_job_claimable",
        "ingest_job",
        ["status", "next_attempt_at", "heartbeat_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_job_claimable", table_name="ingest_job")
    op.drop_constraint("ck_ingest_job_max_attempts_positive", "ingest_job", type_="check")
    op.drop_constraint(
        "ck_ingest_job_attempt_count_non_negative",
        "ingest_job",
        type_="check",
    )
    op.drop_column("ingest_job", "next_attempt_at")
    op.drop_column("ingest_job", "locked_by")
    op.drop_column("ingest_job", "heartbeat_at")
    op.drop_column("ingest_job", "claimed_at")
    op.drop_column("ingest_job", "max_attempts")
    op.drop_column("ingest_job", "attempt_count")
