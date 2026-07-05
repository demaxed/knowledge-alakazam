from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from wiki.models import WikiClaim, WikiPage, WikiRevision, WikiValidationResult
from wiki.repository import WikiValidationResultInput
from wiki.service import WikiPageNotFoundError, extract_wikilinks, slugify_wiki_target

ValidationSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    validator_name: str
    severity: ValidationSeverity
    message: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class ValidationContext:
    tenant_id: str
    page: WikiPage
    revision: WikiRevision
    repository: WikiValidationRepositoryProtocol


@dataclass(frozen=True, slots=True)
class WikiValidationRun:
    page: WikiPage
    revision: WikiRevision
    results: list[WikiValidationResult]


class WikiValidator(Protocol):
    name: str

    async def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        pass


class WikiValidationRepositoryProtocol(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]:
        pass

    async def get_page_by_slug(self, tenant_id: str, slug: str) -> WikiPage | None:
        pass

    async def get_current_revision(self, tenant_id: str, slug: str) -> WikiRevision | None:
        pass

    async def list_pages_by_slugs(self, tenant_id: str, slugs: Sequence[str]) -> list[WikiPage]:
        pass

    async def list_pages_by_title(self, tenant_id: str, title: str) -> list[WikiPage]:
        pass

    async def list_claims_for_revision(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        revision_id: UUID,
    ) -> list[WikiClaim]:
        pass

    async def replace_validation_results(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        revision_id: UUID,
        results: Sequence[WikiValidationResultInput],
    ) -> list[WikiValidationResult]:
        pass

    async def list_validation_results(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        revision_id: UUID | None = None,
    ) -> list[WikiValidationResult]:
        pass


class BrokenWikilinksValidator:
    name = "broken_wikilinks"

    async def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        if context.revision.content_format != "markdown":
            return []

        linked_slugs = extract_wikilinks(context.revision.content)
        if not linked_slugs:
            return []

        pages = await context.repository.list_pages_by_slugs(context.tenant_id, linked_slugs)
        existing_slugs = {page.slug for page in pages}
        return [
            ValidationIssue(
                validator_name=self.name,
                severity="error",
                message=f"Broken wikilink target: [[{target_slug}]]",
                metadata={"target_slug": target_slug},
            )
            for target_slug in linked_slugs
            if target_slug not in existing_slugs
        ]


class UnsupportedClaimsValidator:
    name = "unsupported_claims"

    async def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        claims = await context.repository.list_claims_for_revision(
            tenant_id=context.tenant_id,
            page_id=context.page.id,
            revision_id=context.revision.id,
        )

        issues: list[ValidationIssue] = []
        for claim in claims:
            if claim.support_status not in {"unknown", "unsupported"}:
                continue

            severity: ValidationSeverity = (
                "error" if claim.support_status == "unsupported" else "warning"
            )
            issues.append(
                ValidationIssue(
                    validator_name=self.name,
                    severity=severity,
                    message="Claim support has not been confirmed",
                    metadata={
                        "claim_id": str(claim.id),
                        "support_status": claim.support_status,
                    },
                )
            )
        return issues


class StalePageValidator:
    name = "stale_page"

    def __init__(self, stale_after_days: int = 90) -> None:
        self.stale_after_days = stale_after_days

    async def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        updated_at = _aware_datetime(context.page.updated_at)
        age_days = (datetime.now(UTC) - updated_at).days
        if age_days <= self.stale_after_days:
            return []

        return [
            ValidationIssue(
                validator_name=self.name,
                severity="info",
                message="Page has not been updated recently",
                metadata={
                    "age_days": age_days,
                    "stale_after_days": self.stale_after_days,
                },
            )
        ]


class DuplicateSlugTitleValidator:
    name = "duplicate_slug_title"

    async def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        slug_matches = await context.repository.list_pages_by_slugs(
            context.tenant_id,
            [context.page.slug],
        )
        duplicate_slug_pages = [page for page in slug_matches if page.id != context.page.id]
        if duplicate_slug_pages:
            issues.append(
                ValidationIssue(
                    validator_name=self.name,
                    severity="error",
                    message="Duplicate page slug detected",
                    metadata={
                        "slug": context.page.slug,
                        "matching_page_ids": [str(page.id) for page in duplicate_slug_pages],
                    },
                )
            )

        title_matches = await context.repository.list_pages_by_title(
            context.tenant_id,
            context.page.title,
        )
        duplicate_title_pages = [page for page in title_matches if page.id != context.page.id]
        if duplicate_title_pages:
            issues.append(
                ValidationIssue(
                    validator_name=self.name,
                    severity="warning",
                    message="Another page uses the same title",
                    metadata={
                        "title": context.page.title,
                        "matching_slugs": [page.slug for page in duplicate_title_pages],
                    },
                )
            )

        return issues


class WikiValidationService:
    def __init__(
        self,
        repository: WikiValidationRepositoryProtocol,
        validators: Sequence[WikiValidator] | None = None,
    ) -> None:
        self.repository = repository
        self.validators = list(validators or default_validators())

    async def validate_page(self, *, tenant_id: str, slug: str) -> WikiValidationRun:
        resolved_slug = _require_slug(slug)

        async with self.repository.transaction():
            page = await self._require_page(tenant_id, resolved_slug)
            revision = await self._require_current_revision(tenant_id, resolved_slug)
            context = ValidationContext(
                tenant_id=tenant_id,
                page=page,
                revision=revision,
                repository=self.repository,
            )
            issues = await self._run_validators(context)
            results = await self.repository.replace_validation_results(
                tenant_id=tenant_id,
                page_id=page.id,
                revision_id=revision.id,
                results=[
                    WikiValidationResultInput(
                        validator_name=issue.validator_name,
                        severity=issue.severity,
                        message=issue.message,
                        metadata=issue.metadata,
                    )
                    for issue in issues
                ],
            )
            return WikiValidationRun(page=page, revision=revision, results=results)

    async def list_page_results(self, *, tenant_id: str, slug: str) -> WikiValidationRun:
        resolved_slug = _require_slug(slug)

        page = await self._require_page(tenant_id, resolved_slug)
        revision = await self._require_current_revision(tenant_id, resolved_slug)
        results = await self.repository.list_validation_results(
            tenant_id=tenant_id,
            page_id=page.id,
            revision_id=revision.id,
        )
        return WikiValidationRun(page=page, revision=revision, results=results)

    async def _run_validators(self, context: ValidationContext) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for validator in self.validators:
            issues.extend(await validator.validate(context))
        return issues

    async def _require_page(self, tenant_id: str, slug: str) -> WikiPage:
        page = await self.repository.get_page_by_slug(tenant_id, slug)
        if page is None:
            raise WikiPageNotFoundError(f"Wiki page '{slug}' was not found")
        return page

    async def _require_current_revision(self, tenant_id: str, slug: str) -> WikiRevision:
        revision = await self.repository.get_current_revision(tenant_id, slug)
        if revision is None:
            raise ValueError(f"Wiki page '{slug}' has no current revision")
        return revision


def default_validators() -> tuple[WikiValidator, ...]:
    return (
        BrokenWikilinksValidator(),
        UnsupportedClaimsValidator(),
        StalePageValidator(),
        DuplicateSlugTitleValidator(),
    )


def _require_slug(slug: str) -> str:
    resolved_slug = slugify_wiki_target(slug)
    if not resolved_slug:
        raise ValueError("slug must not be empty")
    return resolved_slug


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
