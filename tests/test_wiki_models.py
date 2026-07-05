from app.db import Base
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from wiki import models


def unique_column_sets(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def check_constraints(table: Table) -> dict[str, str]:
    return {
        str(constraint.name): str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_wiki_metadata_contains_canonical_store_tables() -> None:
    expected_tables = {
        "wiki_page",
        "wiki_revision",
        "wiki_link",
        "wiki_claim",
        "wiki_claim_source",
        "ingest_job",
        "wiki_compile_job",
        "wiki_validation_result",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_wiki_page_columns_and_constraints() -> None:
    page = Base.metadata.tables["wiki_page"]

    assert isinstance(page.c.id.type, PGUUID)
    assert page.c.tenant_id.nullable is False
    assert page.c.slug.nullable is False
    assert page.c.title.nullable is False
    assert page.c.current_revision_id.nullable is True
    assert ("tenant_id", "slug") in unique_column_sets(page)

    revision_fks = page.c.current_revision_id.foreign_keys
    assert {fk.constraint.name for fk in revision_fks if fk.constraint is not None} == {
        "fk_wiki_page_current_revision_id"
    }


def test_revision_and_claim_source_columns() -> None:
    revision = Base.metadata.tables["wiki_revision"]
    claim_source = Base.metadata.tables["wiki_claim_source"]

    assert ("page_id", "revision_no") in unique_column_sets(revision)
    assert revision.c.content.nullable is False
    assert isinstance(revision.c.content_json.type, JSONB)
    assert claim_source.c.source_id.nullable is False
    assert isinstance(claim_source.c.bbox.type, JSONB)
    assert isinstance(claim_source.c.locator.type, JSONB)
    assert claim_source.c.locator.nullable is False


def test_job_status_constraints() -> None:
    ingest_job = Base.metadata.tables["ingest_job"]
    compile_job = Base.metadata.tables["wiki_compile_job"]

    assert check_constraints(ingest_job)["ck_ingest_job_status"] == models.JOB_STATUS_CHECK
    assert check_constraints(compile_job)["ck_wiki_compile_job_status"] == models.JOB_STATUS_CHECK
    assert ("tenant_id", "source_id") in unique_column_sets(ingest_job)


def test_validation_result_uses_metadata_column_name() -> None:
    validation_result = Base.metadata.tables["wiki_validation_result"]

    assert "metadata" in validation_result.c
    assert isinstance(validation_result.c["metadata"].type, JSONB)
    assert "metadata_" in models.WikiValidationResult.__mapper__.attrs
