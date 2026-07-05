from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


QueryMode = Literal["local", "global", "hybrid", "naive", "mix", "bypass"]


class QueryRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    mode: QueryMode = "hybrid"
    vlm_enhanced: bool | None = None


class QueryResponse(BaseModel):
    answer: str
    metadata: dict[str, Any]


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
