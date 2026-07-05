from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class HealthComponent(BaseModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    components: dict[str, HealthComponent]


QueryMode = Literal["local", "global", "hybrid", "naive", "mix", "bypass"]
IngestJobStatus = Literal["pending", "processing", "succeeded", "failed"]
WikiCompileJobStatus = Literal["pending", "processing", "succeeded", "failed"]
WikiValidationSeverity = Literal["info", "warning", "error"]


class QueryRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    mode: QueryMode = "hybrid"
    vlm_enhanced: bool | None = None


class QueryResponse(BaseModel):
    answer: str
    metadata: dict[str, Any]


class IngestResponse(BaseModel):
    tenant_id: str
    source_id: str
    raw_uri: str
    output_dir: str
    asset_count: int
    asset_urls: list[str]
    status: IngestJobStatus
    job_id: UUID | None = None


class WikiPageCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    slug: str | None = Field(default=None, min_length=1)
    content: str = ""
    content_format: str = "markdown"
    content_json: dict[str, Any] | None = None
    summary: str | None = None
    page_type: str = "concept"
    status: str = "draft"
    author_type: str = "agent"


class WikiRevisionCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    content: str
    content_format: str = "markdown"
    content_json: dict[str, Any] | None = None
    summary: str | None = None
    author_type: str = "agent"


class WikiRevisionResponse(BaseModel):
    id: UUID
    page_id: UUID
    revision_no: int
    content_format: str
    content: str
    content_json: dict[str, Any] | None
    summary: str | None
    author_type: str
    created_at: datetime


class WikiPageResponse(BaseModel):
    id: UUID
    tenant_id: str
    slug: str
    title: str
    page_type: str
    status: str
    current_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime
    current_revision: WikiRevisionResponse | None


class WikiBacklinkResponse(BaseModel):
    page_id: UUID
    slug: str
    title: str
    link_type: str
    created_at: datetime


class WikiCompileRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    topic: str | None = Field(default=None, min_length=1)
    target_slug: str | None = Field(default=None, min_length=1)


class WikiCompiledPageResponse(BaseModel):
    page_id: UUID
    slug: str
    title: str
    revision_id: UUID
    revision_no: int
    claim_count: int


class WikiCompileResponse(BaseModel):
    job_id: UUID
    tenant_id: str
    source_id: str
    target_slug: str | None
    status: WikiCompileJobStatus
    error: str | None
    pages: list[WikiCompiledPageResponse]


class WikiValidationResultResponse(BaseModel):
    id: UUID
    tenant_id: str
    page_id: UUID
    revision_id: UUID
    validator_name: str
    severity: WikiValidationSeverity
    message: str
    metadata: dict[str, Any]
    created_at: datetime


class WikiValidationResponse(BaseModel):
    tenant_id: str
    slug: str
    page_id: UUID
    revision_id: UUID
    result_count: int
    results: list[WikiValidationResultResponse]
