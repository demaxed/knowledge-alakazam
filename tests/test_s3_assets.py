from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.s3_assets import S3AssetFileNotFoundError, S3AssetStore, S3BucketMissingError
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import SecretStr


@dataclass(frozen=True)
class UploadCall:
    filename: str
    bucket: str
    key: str
    extra_args: dict[str, str] | None


@dataclass(frozen=True)
class DownloadCall:
    bucket: str
    key: str
    filename: str


class FakeS3Client:
    def __init__(
        self,
        buckets: set[str] | None = None,
        objects: dict[tuple[str, str], bytes] | None = None,
    ) -> None:
        self.buckets = buckets or set()
        self.objects = objects or {}
        self.created_buckets: list[dict[str, Any]] = []
        self.uploads: list[UploadCall] = []
        self.downloads: list[DownloadCall] = []

    def head_bucket(self, *, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise missing_bucket_error(Bucket)

    def create_bucket(self, **kwargs: Any) -> None:
        bucket = str(kwargs["Bucket"])
        self.created_buckets.append(kwargs)
        self.buckets.add(bucket)

    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict[str, str] | None = None,
    ) -> None:
        self.head_bucket(Bucket=Bucket)
        self.uploads.append(
            UploadCall(
                filename=Filename,
                bucket=Bucket,
                key=Key,
                extra_args=ExtraArgs,
            )
        )
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
        self.head_bucket(Bucket=Bucket)
        self.downloads.append(DownloadCall(bucket=Bucket, key=Key, filename=Filename))
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])


def missing_bucket_error(bucket: str) -> ClientError:
    return ClientError(
        error_response={
            "Error": {
                "Code": "NoSuchBucket",
                "Message": f"The specified bucket does not exist: {bucket}",
            }
        },
        operation_name="HeadBucket",
    )


def make_settings() -> Settings:
    return Settings(
        app_database_url="postgresql+asyncpg://rag:rag@localhost:5432/rag",
        s3_endpoint_url="http://minio:9000/",
        s3_region_name="us-east-1",
        s3_access_key_id="test-access-key",
        s3_secret_access_key=SecretStr("test-secret-key"),
        s3_bucket_raw="raw-bucket",
        s3_bucket_assets="asset-bucket",
    )


def test_upload_raw_document_maps_key_and_content_type(tmp_path: Path) -> None:
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"%PDF-1.7")
    fake_client = FakeS3Client(buckets={"raw-bucket"})
    store = S3AssetStore(settings=make_settings(), s3_client=fake_client)

    result = store.upload_raw_document(local_file, tenant_id="tenant-a", source_id="source-1")

    assert result.bucket == "raw-bucket"
    assert result.key == "raw/tenant-a/source-1/report.pdf"
    assert result.content_type == "application/pdf"
    assert result.size_bytes == len(b"%PDF-1.7")
    assert result.url == "http://minio:9000/raw-bucket/raw/tenant-a/source-1/report.pdf"
    assert fake_client.uploads == [
        UploadCall(
            filename=str(local_file),
            bucket="raw-bucket",
            key="raw/tenant-a/source-1/report.pdf",
            extra_args={"ContentType": "application/pdf"},
        )
    ]


def test_upload_output_tree_preserves_relative_paths(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    source_root = output_root / "tenant-a" / "source-1"
    figure = source_root / "images" / "fig1.png"
    table = source_root / "tables" / "table 1.csv"
    figure.parent.mkdir(parents=True)
    table.parent.mkdir(parents=True)
    figure.write_bytes(b"png")
    table.write_text("a,b\n1,2\n")
    fake_client = FakeS3Client(buckets={"asset-bucket"})
    store = S3AssetStore(settings=make_settings(), s3_client=fake_client)

    results = store.upload_output_tree(output_root, tenant_id="tenant-a", source_id="source-1")

    assert [result.key for result in results] == [
        "output/tenant-a/source-1/images/fig1.png",
        "output/tenant-a/source-1/tables/table 1.csv",
    ]
    assert [result.content_type for result in results] == ["image/png", "text/csv"]
    assert results[1].url == (
        "http://minio:9000/asset-bucket/output/tenant-a/source-1/tables/table%201.csv"
    )
    assert [upload.key for upload in fake_client.uploads] == [result.key for result in results]


def test_output_asset_key_requires_asset_under_source_output_root(tmp_path: Path) -> None:
    store = S3AssetStore(settings=make_settings(), s3_client=FakeS3Client())

    with pytest.raises(ValueError, match="inside output tree"):
        store.output_asset_key(
            local_output_root=tmp_path / "output",
            local_asset_path=tmp_path / "elsewhere" / "fig1.png",
            tenant_id="tenant-a",
            source_id="source-1",
        )


def test_ensure_buckets_creates_missing_configured_buckets() -> None:
    fake_client = FakeS3Client(buckets={"raw-bucket"})
    store = S3AssetStore(settings=make_settings(), s3_client=fake_client)

    store.ensure_buckets()

    assert fake_client.buckets == {"raw-bucket", "asset-bucket"}
    assert fake_client.created_buckets == [{"Bucket": "asset-bucket"}]


def test_upload_raw_document_raises_for_missing_local_file(tmp_path: Path) -> None:
    store = S3AssetStore(
        settings=make_settings(),
        s3_client=FakeS3Client(buckets={"raw-bucket"}),
    )

    with pytest.raises(S3AssetFileNotFoundError, match="File not found"):
        store.upload_raw_document(
            tmp_path / "missing.pdf",
            tenant_id="tenant-a",
            source_id="source-1",
        )


def test_upload_raw_document_raises_for_missing_bucket(tmp_path: Path) -> None:
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"%PDF-1.7")
    store = S3AssetStore(settings=make_settings(), s3_client=FakeS3Client())

    with pytest.raises(S3BucketMissingError, match="raw-bucket"):
        store.upload_raw_document(local_file, tenant_id="tenant-a", source_id="source-1")


def test_download_raw_document_creates_destination_parent(tmp_path: Path) -> None:
    fake_client = FakeS3Client(
        buckets={"raw-bucket"},
        objects={("raw-bucket", "raw/tenant-a/source-1/report.pdf"): b"%PDF-1.7"},
    )
    store = S3AssetStore(settings=make_settings(), s3_client=fake_client)
    destination = tmp_path / "downloads" / "report.pdf"

    store.download_raw_document(
        bucket="raw-bucket",
        key="raw/tenant-a/source-1/report.pdf",
        destination_path=destination,
    )

    assert destination.read_bytes() == b"%PDF-1.7"
    assert fake_client.downloads == [
        DownloadCall(
            bucket="raw-bucket",
            key="raw/tenant-a/source-1/report.pdf",
            filename=str(destination),
        )
    ]
