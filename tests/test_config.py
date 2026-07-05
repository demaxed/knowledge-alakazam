from pathlib import Path

import pytest
from app.config import Settings, get_settings
from sqlalchemy.engine import make_url


def test_settings_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("SERVICE_NAME", "knowledge-test")
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+asyncpg://rag:secret@db:5432/rag")
    monkeypatch.setenv("RAG_WORKING_DIR", "/tmp/rag")
    monkeypatch.setenv("RAG_OUTPUT_DIR", "/tmp/output")
    monkeypatch.setenv("RAG_INPUT_DIR", "/tmp/input")
    monkeypatch.setenv("PARSER", "mineru")
    monkeypatch.setenv("PARSE_METHOD", "ocr")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "llm-test")
    monkeypatch.setenv("VISION_MODEL", "vision-test")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-test")
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    monkeypatch.setenv("RAG_RUNTIME_DISABLED", "true")
    monkeypatch.setenv("RAG_ENABLE_IMAGE_PROCESSING", "false")
    monkeypatch.setenv("RAG_ENABLE_TABLE_PROCESSING", "true")
    monkeypatch.setenv("RAG_ENABLE_EQUATION_PROCESSING", "false")
    monkeypatch.setenv("MINIO_ROOT_USER", "minio")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "minio-secret")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("S3_REGION_NAME", "us-west-2")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setenv("S3_BUCKET_RAW", "raw")
    monkeypatch.setenv("S3_BUCKET_ASSETS", "assets")
    monkeypatch.setenv("LIGHTRAG_KV_STORAGE", "PGKVStorage")
    monkeypatch.setenv("LIGHTRAG_VECTOR_STORAGE", "PGVectorStorage")
    monkeypatch.setenv("LIGHTRAG_GRAPH_STORAGE", "PGGraphStorage")
    monkeypatch.setenv("LIGHTRAG_DOC_STATUS_STORAGE", "PGDocStatusStorage")

    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()

    assert settings.env == "test"
    assert settings.service_name == "knowledge-test"
    assert settings.app_database_url == "postgresql+asyncpg://rag:secret@db:5432/rag"
    assert settings.rag_working_dir == Path("/tmp/rag")
    assert settings.rag_output_dir == Path("/tmp/output")
    assert settings.rag_input_dir == Path("/tmp/input")
    assert settings.parser == "mineru"
    assert settings.parse_method == "ocr"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-key"
    assert settings.openai_base_url == "https://llm.example.test/v1"
    assert settings.llm_model == "llm-test"
    assert settings.vision_model == "vision-test"
    assert settings.embedding_model == "embedding-test"
    assert settings.embedding_dim == 768
    assert settings.rag_runtime_disabled is True
    assert settings.rag_enable_image_processing is False
    assert settings.rag_enable_table_processing is True
    assert settings.rag_enable_equation_processing is False
    assert settings.minio_root_user == "minio"
    assert settings.minio_root_password is not None
    assert settings.minio_root_password.get_secret_value() == "minio-secret"
    assert settings.s3_endpoint_url == "http://minio:9000"
    assert settings.s3_region_name == "us-west-2"
    assert settings.s3_access_key_id == "access-key"
    assert settings.s3_secret_access_key is not None
    assert settings.s3_secret_access_key.get_secret_value() == "secret-key"
    assert settings.s3_bucket_raw == "raw"
    assert settings.s3_bucket_assets == "assets"
    assert settings.lightrag_kv_storage == "PGKVStorage"
    assert settings.lightrag_vector_storage == "PGVectorStorage"
    assert settings.lightrag_graph_storage == "PGGraphStorage"
    assert settings.lightrag_doc_status_storage == "PGDocStatusStorage"


def test_database_url_parsing_does_not_break() -> None:
    settings = Settings(
        app_database_url="postgresql+asyncpg://rag:secret@localhost:5432/rag",
    )

    parsed_url = make_url(settings.app_database_url)

    assert parsed_url.drivername == "postgresql+asyncpg"
    assert parsed_url.username == "rag"
    assert parsed_url.host == "localhost"
    assert parsed_url.port == 5432
    assert parsed_url.database == "rag"
