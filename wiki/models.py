from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.db import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

JOB_STATUS_CHECK = "status IN ('pending', 'processing', 'succeeded', 'failed')"


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WikiPage(TimestampMixin, Base):
    __tablename__ = "wiki_page"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_wiki_page_tenant_slug"),
        Index("ix_wiki_page_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    page_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="concept",
        server_default="concept",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="draft",
        server_default="draft",
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "wiki_revision.id",
            name="fk_wiki_page_current_revision_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )


class WikiRevision(CreatedAtMixin, Base):
    __tablename__ = "wiki_revision"
    __table_args__ = (
        UniqueConstraint("page_id", "revision_no", name="uq_wiki_revision_page_revision_no"),
        Index("ix_wiki_revision_page_id", "page_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    page_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("wiki_page.id", name="fk_wiki_revision_page_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_format: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="markdown",
        server_default="markdown",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="agent",
        server_default="agent",
    )


class WikiLink(CreatedAtMixin, Base):
    __tablename__ = "wiki_link"
    __table_args__ = (
        Index("ix_wiki_link_backlinks", "tenant_id", "to_slug"),
        Index("ix_wiki_link_from_page", "tenant_id", "from_page_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    from_page_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("wiki_page.id", name="fk_wiki_link_from_page_id", ondelete="CASCADE"),
        nullable=False,
    )
    to_slug: Mapped[str] = mapped_column(Text, nullable=False)
    link_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="wikilink",
        server_default="wikilink",
    )


class WikiClaim(CreatedAtMixin, Base):
    __tablename__ = "wiki_claim"
    __table_args__ = (
        Index("ix_wiki_claim_page_revision", "tenant_id", "page_id", "revision_id"),
        Index("ix_wiki_claim_support_status", "tenant_id", "support_status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    page_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("wiki_page.id", name="fk_wiki_claim_page_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("wiki_revision.id", name="fk_wiki_claim_revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    support_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class WikiClaimSource(CreatedAtMixin, Base):
    __tablename__ = "wiki_claim_source"
    __table_args__ = (
        Index("ix_wiki_claim_source_claim_id", "claim_id"),
        Index("ix_wiki_claim_source_source_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("wiki_claim.id", name="fk_wiki_claim_source_claim_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    document_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    relation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class IngestJob(TimestampMixin, Base):
    __tablename__ = "ingest_job"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_id", name="uq_ingest_job_tenant_source"),
        CheckConstraint(JOB_STATUS_CHECK, name="ck_ingest_job_status"),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_ingest_job_attempt_count_non_negative",
        ),
        CheckConstraint("max_attempts >= 1", name="ck_ingest_job_max_attempts_positive"),
        Index("ix_ingest_job_tenant_status", "tenant_id", "status"),
        Index(
            "ix_ingest_job_claimable",
            "status",
            "next_attempt_at",
            "heartbeat_at",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    raw_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=sql_text("3"),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class WikiCompileJob(TimestampMixin, Base):
    __tablename__ = "wiki_compile_job"
    __table_args__ = (
        CheckConstraint(JOB_STATUS_CHECK, name="ck_wiki_compile_job_status"),
        Index("ix_wiki_compile_job_tenant_status", "tenant_id", "status"),
        Index("ix_wiki_compile_job_source_id", "tenant_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WikiValidationResult(CreatedAtMixin, Base):
    __tablename__ = "wiki_validation_result"
    __table_args__ = (
        Index("ix_wiki_validation_result_page_revision", "tenant_id", "page_id", "revision_id"),
        Index("ix_wiki_validation_result_severity", "tenant_id", "severity"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    page_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "wiki_page.id",
            name="fk_wiki_validation_result_page_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "wiki_revision.id",
            name="fk_wiki_validation_result_revision_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    validator_name: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
