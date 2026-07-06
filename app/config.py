from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    env: str = Field(default="local", validation_alias=AliasChoices("ENV", "APP_ENV"))
    service_name: str = Field(
        default="knowledge-alakazam",
        validation_alias=AliasChoices("SERVICE_NAME", "APP_NAME"),
    )
    log_level: str = "INFO"
    health_check_timeout_seconds: float = Field(default=1.0, gt=0)
    health_check_s3: bool = False

    app_database_url: str = Field(
        default="postgresql+asyncpg://localhost/rag",
        validation_alias=AliasChoices("APP_DATABASE_URL", "DATABASE_URL"),
    )

    rag_working_dir: Path = Field(
        default=Path("./storage/lightrag"),
        validation_alias=AliasChoices("RAG_WORKING_DIR", "LIGHTRAG_WORKING_DIR"),
    )
    rag_output_dir: Path = Path("./storage/output")
    rag_input_dir: Path = Path("./storage/inputs")
    parser: str = "mineru"
    parse_method: str = "auto"
    ingest_sync: bool = True
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0)

    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-4.1-mini"
    vision_model: str = "gpt-4.1-mini"
    embedding_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "EMBEDDING_BASE_URL",
            "EMBEDDING_ENDPOINT_URL",
            "EMBEDDING_ENDPOINT",
        ),
    )
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = Field(
        default=1536,
        ge=1,
        validation_alias=AliasChoices("EMBEDDING_DIM", "EMBEDDING_DIMENSION"),
    )

    rag_runtime_disabled: bool = True
    rag_enable_image_processing: bool = True
    rag_enable_table_processing: bool = True
    rag_enable_equation_processing: bool = True

    minio_root_user: str | None = None
    minio_root_password: SecretStr | None = None
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region_name: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket_raw: str = "rag-raw"
    s3_bucket_assets: str = "rag-assets"

    lightrag_kv_storage: str = "PGKVStorage"
    lightrag_vector_storage: str = "PGVectorStorage"
    lightrag_graph_storage: str = "PGGraphStorage"
    lightrag_doc_status_storage: str = "PGDocStatusStorage"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("app_database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            parsed_url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("APP_DATABASE_URL must be a valid SQLAlchemy database URL") from exc

        if not parsed_url.drivername.startswith("postgresql"):
            raise ValueError("APP_DATABASE_URL must use a PostgreSQL driver")
        return value

    @property
    def app_name(self) -> str:
        return self.service_name

    @property
    def app_env(self) -> str:
        return self.env

    @property
    def database_url(self) -> str:
        return self.app_database_url

    @property
    def lightrag_working_dir(self) -> Path:
        return self.rag_working_dir

    @property
    def embedding_dimension(self) -> int:
        return self.embedding_dim


@lru_cache
def get_settings() -> Settings:
    return Settings()
