"""Create llm-wiki canonical store.

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260705_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_STATUS_CHECK = "status IN ('pending', 'processing', 'succeeded', 'failed')"


def upgrade() -> None:
    op.create_table(
        "wiki_page",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), server_default="concept", nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_wiki_page_tenant_slug"),
    )
    op.create_index("ix_wiki_page_tenant_status", "wiki_page", ["tenant_id", "status"])

    op.create_table(
        "wiki_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("content_format", sa.Text(), server_default="markdown", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("author_type", sa.Text(), server_default="agent", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["wiki_page.id"],
            name="fk_wiki_revision_page_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "revision_no", name="uq_wiki_revision_page_revision_no"),
    )
    op.create_index("ix_wiki_revision_page_id", "wiki_revision", ["page_id"])

    op.create_foreign_key(
        "fk_wiki_page_current_revision_id",
        "wiki_page",
        "wiki_revision",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "wiki_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("from_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_slug", sa.Text(), nullable=False),
        sa.Column("link_type", sa.Text(), server_default="wikilink", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_page_id"],
            ["wiki_page.id"],
            name="fk_wiki_link_from_page_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_link_backlinks", "wiki_link", ["tenant_id", "to_slug"])
    op.create_index("ix_wiki_link_from_page", "wiki_link", ["tenant_id", "from_page_id"])

    op.create_table(
        "wiki_claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("support_status", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["wiki_page.id"],
            name="fk_wiki_claim_page_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["wiki_revision.id"],
            name="fk_wiki_claim_revision_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wiki_claim_page_revision",
        "wiki_claim",
        ["tenant_id", "page_id", "revision_id"],
    )
    op.create_index(
        "ix_wiki_claim_support_status",
        "wiki_claim",
        ["tenant_id", "support_status"],
    )

    op.create_table(
        "wiki_claim_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("document_uri", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("relation_id", sa.Text(), nullable=True),
        sa.Column("asset_url", sa.Text(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column(
            "locator",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["wiki_claim.id"],
            name="fk_wiki_claim_source_claim_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_claim_source_claim_id", "wiki_claim_source", ["claim_id"])
    op.create_index("ix_wiki_claim_source_source_id", "wiki_claim_source", ["source_id"])

    op.create_table(
        "ingest_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("raw_bucket", sa.Text(), nullable=False),
        sa.Column("raw_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(JOB_STATUS_CHECK, name="ck_ingest_job_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_id", name="uq_ingest_job_tenant_source"),
    )
    op.create_index("ix_ingest_job_tenant_status", "ingest_job", ["tenant_id", "status"])

    op.create_table(
        "wiki_compile_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("target_slug", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(JOB_STATUS_CHECK, name="ck_wiki_compile_job_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_compile_job_source_id", "wiki_compile_job", ["tenant_id", "source_id"])
    op.create_index(
        "ix_wiki_compile_job_tenant_status",
        "wiki_compile_job",
        ["tenant_id", "status"],
    )

    op.create_table(
        "wiki_validation_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validator_name", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["wiki_page.id"],
            name="fk_wiki_validation_result_page_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["wiki_revision.id"],
            name="fk_wiki_validation_result_revision_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wiki_validation_result_page_revision",
        "wiki_validation_result",
        ["tenant_id", "page_id", "revision_id"],
    )
    op.create_index(
        "ix_wiki_validation_result_severity",
        "wiki_validation_result",
        ["tenant_id", "severity"],
    )


def downgrade() -> None:
    op.drop_index("ix_wiki_validation_result_severity", table_name="wiki_validation_result")
    op.drop_index("ix_wiki_validation_result_page_revision", table_name="wiki_validation_result")
    op.drop_table("wiki_validation_result")

    op.drop_index("ix_wiki_compile_job_tenant_status", table_name="wiki_compile_job")
    op.drop_index("ix_wiki_compile_job_source_id", table_name="wiki_compile_job")
    op.drop_table("wiki_compile_job")

    op.drop_index("ix_ingest_job_tenant_status", table_name="ingest_job")
    op.drop_table("ingest_job")

    op.drop_index("ix_wiki_claim_source_source_id", table_name="wiki_claim_source")
    op.drop_index("ix_wiki_claim_source_claim_id", table_name="wiki_claim_source")
    op.drop_table("wiki_claim_source")

    op.drop_index("ix_wiki_claim_support_status", table_name="wiki_claim")
    op.drop_index("ix_wiki_claim_page_revision", table_name="wiki_claim")
    op.drop_table("wiki_claim")

    op.drop_index("ix_wiki_link_from_page", table_name="wiki_link")
    op.drop_index("ix_wiki_link_backlinks", table_name="wiki_link")
    op.drop_table("wiki_link")

    op.drop_constraint("fk_wiki_page_current_revision_id", "wiki_page", type_="foreignkey")

    op.drop_index("ix_wiki_revision_page_id", table_name="wiki_revision")
    op.drop_table("wiki_revision")

    op.drop_index("ix_wiki_page_tenant_status", table_name="wiki_page")
    op.drop_table("wiki_page")
