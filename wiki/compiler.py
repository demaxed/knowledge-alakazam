from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.rag_runtime import RAGQueryResult

from wiki.models import WikiCompileJob
from wiki.service import (
    ClaimSourceInput,
    WikiPageDetail,
    WikiPageNotFoundError,
    WikiService,
    slugify_wiki_target,
)

DEFAULT_COMPILE_MODE = "hybrid"
MAX_CLAIMS_PER_PAGE = 8
MAX_CLAIM_LENGTH = 700
MAX_SUMMARY_LENGTH = 1200
MAX_RELATED_PAGES = 8
MAX_KEY_CONCEPTS = 10

SOURCE_COLLECTION_KEYS = (
    "sources",
    "source",
    "references",
    "citations",
    "chunks",
    "contexts",
    "documents",
    "retrieved_docs",
)
SOURCE_ID_KEYS = ("source_id", "doc_id", "document_id", "file_id", "id")
DOCUMENT_URI_KEYS = ("document_uri", "uri", "url", "file_path", "path")
CHUNK_ID_KEYS = ("chunk_id", "chunk", "chunk_key")
ENTITY_ID_KEYS = ("entity_id", "entity")
RELATION_ID_KEYS = ("relation_id", "relation")
ASSET_URL_KEYS = ("asset_url", "image_url", "figure_url", "asset")
PAGE_NO_KEYS = ("page_no", "page", "page_number")
QUOTE_KEYS = ("quote", "text", "content", "snippet")


class RAGRuntimeProtocol(Protocol):
    async def query(
        self,
        question: str,
        mode: str = DEFAULT_COMPILE_MODE,
        vlm_enhanced: bool | None = None,
    ) -> RAGQueryResult:
        pass


class CompileJobRepositoryProtocol(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]:
        pass

    async def create_compile_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        target_slug: str | None = None,
    ) -> WikiCompileJob:
        pass

    async def mark_compile_job_processing(self, job_id: UUID) -> WikiCompileJob:
        pass

    async def mark_compile_job_succeeded(self, job_id: UUID) -> WikiCompileJob:
        pass

    async def mark_compile_job_failed(self, job_id: UUID, error: str) -> WikiCompileJob:
        pass


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    source_id: str
    document_uri: str | None = None
    chunk_id: str | None = None
    entity_id: str | None = None
    relation_id: str | None = None
    asset_url: str | None = None
    page_no: int | None = None
    bbox: dict[str, Any] | None = None
    quote: str | None = None
    locator: dict[str, Any] | None = None

    def to_claim_source_input(self) -> ClaimSourceInput:
        return ClaimSourceInput(
            source_id=self.source_id,
            document_uri=self.document_uri,
            chunk_id=self.chunk_id,
            entity_id=self.entity_id,
            relation_id=self.relation_id,
            asset_url=self.asset_url,
            page_no=self.page_no,
            bbox=self.bbox,
            quote=self.quote,
            locator=self.locator,
        )


@dataclass(frozen=True, slots=True)
class CompilerEvidence:
    query: str
    answer: str
    metadata: dict[str, Any]
    source_id: str | None
    sources: tuple[EvidenceSource, ...]


@dataclass(frozen=True, slots=True)
class WikiCompiledPage:
    page_id: UUID
    slug: str
    title: str
    revision_id: UUID
    revision_no: int
    claim_count: int


@dataclass(frozen=True, slots=True)
class WikiCompileResult:
    job: WikiCompileJob
    pages: list[WikiCompiledPage]


class WikiCompiler:
    """Builds deterministic first-pass wiki pages from RAG evidence."""

    def __init__(
        self,
        *,
        wiki_service: WikiService,
        compile_repository: CompileJobRepositoryProtocol,
        rag_runtime: RAGRuntimeProtocol,
        mode: str = DEFAULT_COMPILE_MODE,
    ) -> None:
        self.wiki_service = wiki_service
        self.compile_repository = compile_repository
        self.rag_runtime = rag_runtime
        self.mode = mode

    async def compile_source_to_pages(
        self,
        tenant_id: str,
        source_id: str,
        target_slug: str | None = None,
    ) -> WikiCompileResult:
        resolved_source_id = _require_non_empty(source_id, "source_id")
        resolved_slug = _resolve_target_slug(target_slug, _source_page_title(resolved_source_id))
        job = await self._start_job(
            tenant_id=tenant_id,
            source_id=resolved_source_id,
            target_slug=resolved_slug,
        )

        try:
            evidence = await self._search_evidence(
                _source_evidence_query(resolved_source_id),
                source_id=resolved_source_id,
            )
            page = await self.update_existing_page_with_evidence(
                tenant_id=tenant_id,
                slug=resolved_slug,
                evidence=evidence,
                title=_source_page_title(resolved_source_id),
            )
            job = await self._mark_job_succeeded(job.id)
            return WikiCompileResult(job=job, pages=[page])
        except Exception as exc:
            await self._mark_job_failed(job.id, str(exc))
            raise

    async def compile_topic_page(
        self,
        tenant_id: str,
        topic: str,
        evidence_query: str,
        *,
        source_id: str | None = None,
        target_slug: str | None = None,
    ) -> WikiCompileResult:
        resolved_topic = _require_non_empty(topic, "topic")
        resolved_query = evidence_query.strip() or _topic_evidence_query(
            resolved_topic,
            source_id=source_id,
        )
        resolved_slug = _resolve_target_slug(target_slug, resolved_topic)
        job_source_id = source_id.strip() if source_id and source_id.strip() else None
        if job_source_id is None:
            job_source_id = f"topic:{resolved_slug}"

        job = await self._start_job(
            tenant_id=tenant_id,
            source_id=job_source_id,
            target_slug=resolved_slug,
        )

        try:
            evidence = await self._search_evidence(
                resolved_query,
                source_id=source_id,
            )
            page = await self.update_existing_page_with_evidence(
                tenant_id=tenant_id,
                slug=resolved_slug,
                evidence=evidence,
                title=resolved_topic,
            )
            job = await self._mark_job_succeeded(job.id)
            return WikiCompileResult(job=job, pages=[page])
        except Exception as exc:
            await self._mark_job_failed(job.id, str(exc))
            raise

    async def update_existing_page_with_evidence(
        self,
        tenant_id: str,
        slug: str,
        evidence: CompilerEvidence,
        title: str | None = None,
    ) -> WikiCompiledPage:
        resolved_slug = _resolve_target_slug(slug, slug)
        resolved_title = await self._resolve_page_title(
            tenant_id,
            resolved_slug,
            fallback_title=title,
        )
        claims = _extract_claim_texts(evidence)
        markdown = _render_page_markdown(
            title=resolved_title,
            current_slug=resolved_slug,
            evidence=evidence,
            claims=claims,
        )

        detail = await self.wiki_service.create_or_update_page(
            tenant_id=tenant_id,
            slug=resolved_slug,
            title=resolved_title,
            content=markdown,
            content_format="markdown",
            content_json=_content_json(evidence),
            summary=_summary_from_answer(evidence.answer),
            author_type="agent",
        )
        if detail.current_revision is None:
            raise RuntimeError(f"Wiki page '{resolved_slug}' has no current revision")

        sources = [source.to_claim_source_input() for source in evidence.sources]
        for claim_text in claims:
            await self.wiki_service.add_claim_with_sources(
                tenant_id=tenant_id,
                slug=resolved_slug,
                claim_text=claim_text,
                sources=sources,
                support_status="supported",
                confidence=Decimal("0.5000"),
            )

        return _compiled_page(detail, claim_count=len(claims))

    async def _search_evidence(
        self,
        query: str,
        *,
        source_id: str | None,
    ) -> CompilerEvidence:
        result = await self.rag_runtime.query(query, mode=self.mode)
        metadata = _json_safe_dict(result.metadata)
        return CompilerEvidence(
            query=query,
            answer=result.answer,
            metadata=metadata,
            source_id=source_id,
            sources=tuple(_extract_sources(metadata, query=query, fallback_source_id=source_id)),
        )

    async def _resolve_page_title(
        self,
        tenant_id: str,
        slug: str,
        *,
        fallback_title: str | None,
    ) -> str:
        try:
            detail = await self.wiki_service.get_page(tenant_id=tenant_id, slug=slug)
        except WikiPageNotFoundError:
            return fallback_title or _title_from_slug(slug)
        return detail.page.title

    async def _start_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        target_slug: str,
    ) -> WikiCompileJob:
        async with self.compile_repository.transaction():
            job = await self.compile_repository.create_compile_job(
                tenant_id=tenant_id,
                source_id=source_id,
                target_slug=target_slug,
            )

        async with self.compile_repository.transaction():
            return await self.compile_repository.mark_compile_job_processing(job.id)

    async def _mark_job_succeeded(self, job_id: UUID) -> WikiCompileJob:
        async with self.compile_repository.transaction():
            return await self.compile_repository.mark_compile_job_succeeded(job_id)

    async def _mark_job_failed(self, job_id: UUID, error: str) -> WikiCompileJob:
        async with self.compile_repository.transaction():
            return await self.compile_repository.mark_compile_job_failed(job_id, error)


def _compiled_page(detail: WikiPageDetail, *, claim_count: int) -> WikiCompiledPage:
    if detail.current_revision is None:
        raise RuntimeError(f"Wiki page '{detail.page.slug}' has no current revision")
    return WikiCompiledPage(
        page_id=detail.page.id,
        slug=detail.page.slug,
        title=detail.page.title,
        revision_id=detail.current_revision.id,
        revision_no=detail.current_revision.revision_no,
        claim_count=claim_count,
    )


def _source_evidence_query(source_id: str) -> str:
    return (
        "Return source-backed evidence from document "
        f"{source_id!r}. Focus on facts, key concepts, relationships, and open questions."
    )


def _topic_evidence_query(topic: str, *, source_id: str | None = None) -> str:
    if source_id:
        return (
            f"Return source-backed evidence about {topic!r} from document {source_id!r}. "
            "Focus on facts, key concepts, relationships, and open questions."
        )
    return (
        f"Return source-backed evidence about {topic!r}. "
        "Focus on facts, key concepts, relationships, and open questions."
    )


def _render_page_markdown(
    *,
    title: str,
    current_slug: str,
    evidence: CompilerEvidence,
    claims: list[str],
) -> str:
    summary = _summary_from_answer(evidence.answer)
    key_concepts = _extract_key_concepts(evidence.metadata, fallback=title)
    related_pages = _extract_related_pages(evidence, current_slug=current_slug)
    open_questions = _extract_open_questions(evidence.metadata)

    return "\n\n".join(
        [
            f"# {title}",
            "## Summary\n\n" + summary,
            "## Key Concepts\n\n" + _bullet_lines(key_concepts),
            "## Source-backed Claims\n\n" + _bullet_lines(claims),
            "## Related Pages\n\n" + _bullet_lines([_wikilink(page) for page in related_pages]),
            "## Open Questions\n\n" + _bullet_lines(open_questions),
        ]
    )


def _extract_claim_texts(evidence: CompilerEvidence) -> list[str]:
    claims = [_clean_claim(claim) for claim in _metadata_claims(evidence.metadata)]
    if not claims:
        claims = [_clean_claim(line) for line in evidence.answer.splitlines()]
    claims = [claim for claim in claims if claim]

    if not claims and evidence.answer.strip():
        claims = [_truncate(_strip_markdown_noise(evidence.answer), MAX_CLAIM_LENGTH)]

    return _dedupe_non_empty(claims, limit=MAX_CLAIMS_PER_PAGE)


def _metadata_claims(metadata: Mapping[str, Any]) -> list[str]:
    claims: list[str] = []
    for key in ("claims", "source_backed_claims", "statements"):
        value = metadata.get(key)
        if value is None:
            continue
        claims.extend(_coerce_claim_values(value))
    return claims


def _coerce_claim_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        for key in ("claim_text", "claim", "text", "statement"):
            text = _coerce_text(value.get(key))
            if text:
                return [text]
        return []
    if isinstance(value, list | tuple):
        claims: list[str] = []
        for item in value:
            claims.extend(_coerce_claim_values(item))
        return claims
    return []


def _clean_claim(value: str) -> str:
    value = _strip_markdown_noise(value)
    if len(value) < 12:
        return ""
    return _truncate(value, MAX_CLAIM_LENGTH)


def _strip_markdown_noise(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^#{1,6}\s+", "", stripped)
    stripped = re.sub(r"^\s*[-*+]\s+", "", stripped)
    stripped = re.sub(r"^\s*\d+[.)]\s+", "", stripped)
    stripped = stripped.strip()
    if stripped.endswith(":") and len(stripped.split()) <= 5:
        return ""
    return " ".join(stripped.split())


def _summary_from_answer(answer: str) -> str:
    stripped = _strip_markdown_noise(answer)
    if not stripped:
        return "No summary was returned by the RAG evidence query."
    return _truncate(stripped, MAX_SUMMARY_LENGTH)


def _extract_key_concepts(metadata: Mapping[str, Any], *, fallback: str) -> list[str]:
    concepts: list[str] = []
    for key in ("key_concepts", "concepts", "entities"):
        concepts.extend(_coerce_named_values(metadata.get(key)))

    concepts = _dedupe_non_empty(concepts, limit=MAX_KEY_CONCEPTS)
    return concepts or [fallback]


def _coerce_named_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        for key in ("name", "title", "label", "entity_name", "concept"):
            text = _coerce_text(value.get(key))
            if text:
                return [text]
        return []
    if isinstance(value, list | tuple):
        names: list[str] = []
        for item in value:
            names.extend(_coerce_named_values(item))
        return names
    return []


def _extract_related_pages(evidence: CompilerEvidence, *, current_slug: str) -> list[str]:
    related = _coerce_named_values(evidence.metadata.get("related_pages"))
    for source in evidence.sources:
        if source.source_id == "rag-query":
            continue
        related.append(_source_page_title(source.source_id))

    pages: list[str] = []
    seen: set[str] = set()
    for page in related:
        slug = slugify_wiki_target(page)
        if not slug or slug == current_slug or slug in seen:
            continue
        seen.add(slug)
        pages.append(page)
        if len(pages) >= MAX_RELATED_PAGES:
            break
    return pages


def _extract_open_questions(metadata: Mapping[str, Any]) -> list[str]:
    questions = _coerce_claim_values(metadata.get("open_questions"))
    questions = _dedupe_non_empty(questions, limit=MAX_CLAIMS_PER_PAGE)
    return questions or ["No open questions were extracted from structured evidence."]


def _extract_sources(
    metadata: Mapping[str, Any],
    *,
    query: str,
    fallback_source_id: str | None,
) -> list[EvidenceSource]:
    sources: list[EvidenceSource] = []
    for item in _source_candidate_items(metadata):
        source = _evidence_source_from_item(item, fallback_source_id=fallback_source_id)
        if source is not None:
            sources.append(source)

    if not sources:
        fallback = (
            fallback_source_id.strip()
            if fallback_source_id and fallback_source_id.strip()
            else None
        )
        sources = [
            EvidenceSource(
                source_id=fallback or "rag-query",
                locator={
                    "evidence_query": query,
                    "rag_metadata": _json_safe(metadata),
                    "structured_source_ids_available": False,
                    "provenance_note": (
                        "RAG runtime did not return chunk/entity provenance; "
                        "raw query metadata is preserved here."
                    ),
                },
            )
        ]

    deduped: list[EvidenceSource] = []
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    for source in sources:
        key = (
            source.source_id,
            source.chunk_id,
            source.entity_id,
            source.relation_id,
            source.quote,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _source_candidate_items(metadata: Mapping[str, Any]) -> list[Any]:
    items: list[Any] = []
    if _has_source_identity(metadata):
        items.append(metadata)

    for key in SOURCE_COLLECTION_KEYS:
        if key in metadata:
            items.extend(_flatten_source_items(metadata[key]))
    return items


def _flatten_source_items(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        if _has_source_identity(value):
            return [value]

        items: list[Any] = []
        for nested in value.values():
            items.extend(_flatten_source_items(nested))
        return items
    if isinstance(value, list | tuple):
        items = []
        for item in value:
            items.extend(_flatten_source_items(item))
        return items
    return []


def _evidence_source_from_item(
    item: Any,
    *,
    fallback_source_id: str | None,
) -> EvidenceSource | None:
    if isinstance(item, str):
        source_id = fallback_source_id or item
        return EvidenceSource(
            source_id=source_id,
            document_uri=item if _looks_like_uri(item) else None,
            locator={"raw_source": item, "structured_source_ids_available": False},
        )

    if not isinstance(item, Mapping):
        return None

    resolved_source_id = _first_text(item, SOURCE_ID_KEYS) or fallback_source_id
    if not resolved_source_id:
        return None

    return EvidenceSource(
        source_id=resolved_source_id,
        document_uri=_first_text(item, DOCUMENT_URI_KEYS),
        chunk_id=_first_text(item, CHUNK_ID_KEYS),
        entity_id=_first_text(item, ENTITY_ID_KEYS),
        relation_id=_first_text(item, RELATION_ID_KEYS),
        asset_url=_first_text(item, ASSET_URL_KEYS),
        page_no=_first_int(item, PAGE_NO_KEYS),
        bbox=_first_mapping(item, ("bbox", "bounding_box")),
        quote=_first_text(item, QUOTE_KEYS),
        locator={
            "raw_source": _json_safe(item),
            "structured_source_ids_available": True,
        },
    )


def _has_source_identity(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in (*SOURCE_ID_KEYS, *CHUNK_ID_KEYS, *DOCUMENT_URI_KEYS))


def _first_text(value: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = _coerce_text(value.get(key))
        if text:
            return text
    return None


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(value: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
    return None


def _first_mapping(value: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, Mapping):
            return _json_safe_dict(raw)
    return None


def _content_json(evidence: CompilerEvidence) -> dict[str, Any]:
    return {
        "compiler": "WikiCompiler",
        "evidence_query": evidence.query,
        "source_id": evidence.source_id,
        "source_ids": [source.source_id for source in evidence.sources],
        "rag_metadata": evidence.metadata,
        "provenance_limitations": (
            "Chunk, entity, and relation IDs are populated only when returned by the "
            "RAG runtime metadata."
        ),
    }


def _bullet_lines(values: list[str]) -> str:
    cleaned = _dedupe_non_empty(values)
    if not cleaned:
        cleaned = ["No items extracted from structured evidence."]
    return "\n".join(f"- {value}" for value in cleaned)


def _wikilink(value: str) -> str:
    cleaned = value.replace("[", "").replace("]", "").replace("\n", " ").strip()
    return f"[[{cleaned}]]" if cleaned else ""


def _source_page_title(source_id: str) -> str:
    return f"Source {source_id}"


def _title_from_slug(slug: str) -> str:
    words = slug.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) or "Untitled"


def _resolve_target_slug(target_slug: str | None, fallback_title: str) -> str:
    slug = slugify_wiki_target(target_slug or fallback_title)
    if not slug:
        raise ValueError("target_slug cannot be empty")
    return slug


def _require_non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} cannot be empty")
    return stripped


def _dedupe_non_empty(values: list[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = " ".join(value.strip().split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _truncate(value: str, max_length: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "..."


def _looks_like_uri(value: str) -> bool:
    return "://" in value or value.startswith("/")


def _json_safe_dict(value: Mapping[Any, Any]) -> dict[str, Any]:
    safe = _json_safe(value)
    if isinstance(safe, dict):
        return safe
    return {"value": safe}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
