from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "knowledge-alakazam"
    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region_name: str = "us-east-1"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_raw: str = "raw-documents"
    s3_bucket_assets: str = "parsed-assets"

    lightrag_working_dir: str = "./storage/lightrag"
    lightrag_kv_storage: str = "PGKVStorage"
    lightrag_vector_storage: str = "PGVectorStorage"
    lightrag_graph_storage: str = "PGGraphStorage"
    lightrag_doc_status_storage: str = "PGDocStatusStorage"
    embedding_dimension: int = Field(default=1536, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
