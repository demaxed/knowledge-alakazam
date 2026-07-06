from __future__ import annotations

import asyncio
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class S3AssetStoreError(RuntimeError):
    """Base error for S3 asset store failures."""


class S3AssetFileNotFoundError(S3AssetStoreError):
    """Raised when a local file or output tree does not exist."""


class S3BucketMissingError(S3AssetStoreError):
    """Raised when an expected S3 bucket is absent."""


class S3UploadError(S3AssetStoreError):
    """Raised when an upload fails after local validation passes."""


class S3DownloadError(S3AssetStoreError):
    """Raised when a download fails after local validation passes."""


class S3ClientProtocol(Protocol):
    def head_bucket(self, *, Bucket: str) -> Any: ...

    def create_bucket(self, **kwargs: Any) -> Any: ...

    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict[str, str] | None = None,
    ) -> Any: ...

    def download_file(self, Bucket: str, Key: str, Filename: str) -> Any: ...


@dataclass(frozen=True)
class RawUploadResult:
    bucket: str
    key: str
    tenant_id: str
    source_id: str
    content_type: str
    size_bytes: int
    url: str


@dataclass(frozen=True)
class AssetUploadResult:
    bucket: str
    key: str
    local_path: Path
    content_type: str
    size_bytes: int
    url: str


class S3AssetStore:
    def __init__(
        self,
        settings: Settings | None = None,
        s3_client: S3ClientProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = s3_client or self._create_client()

    def ensure_buckets(self) -> None:
        for bucket in (self.settings.s3_bucket_raw, self.settings.s3_bucket_assets):
            if not self._bucket_exists(bucket):
                self._create_bucket(bucket)

    def check_buckets(self) -> dict[str, bool]:
        return {
            self.settings.s3_bucket_raw: self._bucket_exists(self.settings.s3_bucket_raw),
            self.settings.s3_bucket_assets: self._bucket_exists(self.settings.s3_bucket_assets),
        }

    def upload_raw_document(
        self,
        local_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> RawUploadResult:
        path = self._require_file(local_path)
        bucket = self.settings.s3_bucket_raw
        self._assert_bucket_exists(bucket)

        key = self.raw_document_key(path, tenant_id, source_id)
        content_type = self._content_type(path)
        self._upload_file(path, bucket, key, content_type)
        logger.info(
            "s3_raw_document_uploaded",
            extra={
                "tenant_id": tenant_id,
                "source_id": source_id,
                "bucket": bucket,
                "key": key,
                "content_type": content_type,
                "size_bytes": path.stat().st_size,
            },
        )

        return RawUploadResult(
            bucket=bucket,
            key=key,
            tenant_id=tenant_id,
            source_id=source_id,
            content_type=content_type,
            size_bytes=path.stat().st_size,
            url=self.public_asset_url(bucket, key),
        )

    async def upload_raw_document_async(
        self,
        local_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> RawUploadResult:
        return await asyncio.to_thread(
            self.upload_raw_document,
            local_path,
            tenant_id=tenant_id,
            source_id=source_id,
        )

    def upload_output_tree(
        self,
        local_output_root: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> list[AssetUploadResult]:
        output_root = Path(local_output_root)
        source_output_root = (
            output_root
            / self._key_segment(tenant_id, "tenant_id")
            / self._key_segment(source_id, "source_id")
        )
        if not source_output_root.is_dir():
            raise S3AssetFileNotFoundError(f"Output tree not found: {source_output_root}")

        bucket = self.settings.s3_bucket_assets
        self._assert_bucket_exists(bucket)

        results: list[AssetUploadResult] = []
        for path in sorted(item for item in source_output_root.rglob("*") if item.is_file()):
            key = self.output_asset_key(output_root, path, tenant_id, source_id)
            content_type = self._content_type(path)
            self._upload_file(path, bucket, key, content_type)
            results.append(
                AssetUploadResult(
                    bucket=bucket,
                    key=key,
                    local_path=path,
                    content_type=content_type,
                    size_bytes=path.stat().st_size,
                    url=self.public_asset_url(bucket, key),
                )
            )

        logger.info(
            "s3_output_tree_uploaded",
            extra={
                "tenant_id": tenant_id,
                "source_id": source_id,
                "bucket": bucket,
                "asset_count": len(results),
            },
        )
        return results

    async def upload_output_tree_async(
        self,
        local_output_root: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> list[AssetUploadResult]:
        return await asyncio.to_thread(
            self.upload_output_tree,
            local_output_root,
            tenant_id=tenant_id,
            source_id=source_id,
        )

    def public_asset_url(self, bucket: str, key: str) -> str:
        quoted_bucket = quote(bucket.strip("/"), safe="")
        quoted_key = quote(key.lstrip("/"), safe="/")
        return f"{self.settings.s3_endpoint_url.rstrip('/')}/{quoted_bucket}/{quoted_key}"

    def download_raw_document(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None:
        self._assert_bucket_exists(bucket)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._client.download_file(bucket, key, str(destination))
        except ClientError as exc:
            if self._is_missing_bucket_error(exc):
                raise S3BucketMissingError(f"S3 bucket does not exist: {bucket}") from exc
            raise S3DownloadError(f"Failed to download s3://{bucket}/{key}") from exc
        except (BotoCoreError, OSError) as exc:
            raise S3DownloadError(f"Failed to download s3://{bucket}/{key}") from exc

    async def download_raw_document_async(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None:
        await asyncio.to_thread(
            self.download_raw_document,
            bucket,
            key,
            destination_path,
        )

    def raw_document_key(self, local_path: str | Path, tenant_id: str, source_id: str) -> str:
        path = Path(local_path)
        return "/".join(
            (
                self._key_segment(tenant_id, "tenant_id"),
                self._key_segment(source_id, "source_id"),
                self._key_segment(path.name, "filename"),
            )
        )

    def output_asset_key(
        self,
        local_output_root: str | Path,
        local_asset_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> str:
        output_root = Path(local_output_root)
        source_output_root = (
            output_root
            / self._key_segment(tenant_id, "tenant_id")
            / self._key_segment(source_id, "source_id")
        )
        asset_path = Path(local_asset_path)
        try:
            relative_path = asset_path.relative_to(source_output_root)
        except ValueError as exc:
            message = f"Asset path must be inside output tree: {source_output_root}"
            raise ValueError(message) from exc

        return "/".join(
            (
                "output",
                self._key_segment(tenant_id, "tenant_id"),
                self._key_segment(source_id, "source_id"),
                relative_path.as_posix(),
            )
        )

    def _create_client(self) -> S3ClientProtocol:
        secret_access_key = (
            self.settings.s3_secret_access_key.get_secret_value()
            if self.settings.s3_secret_access_key is not None
            else None
        )
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            region_name=self.settings.s3_region_name,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _bucket_exists(self, bucket: str) -> bool:
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if self._is_missing_bucket_error(exc):
                return False
            raise S3AssetStoreError(f"Failed to inspect S3 bucket: {bucket}") from exc
        except BotoCoreError as exc:
            raise S3AssetStoreError(f"Failed to inspect S3 bucket: {bucket}") from exc

        return True

    def _assert_bucket_exists(self, bucket: str) -> None:
        if not self._bucket_exists(bucket):
            raise S3BucketMissingError(f"S3 bucket does not exist: {bucket}")

    def _create_bucket(self, bucket: str) -> None:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if self.settings.s3_region_name != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": self.settings.s3_region_name,
            }

        try:
            self._client.create_bucket(**kwargs)
        except ClientError as exc:
            raise S3AssetStoreError(f"Failed to create S3 bucket: {bucket}") from exc
        except BotoCoreError as exc:
            raise S3AssetStoreError(f"Failed to create S3 bucket: {bucket}") from exc

    def _upload_file(self, path: Path, bucket: str, key: str, content_type: str) -> None:
        try:
            self._client.upload_file(
                Filename=str(path),
                Bucket=bucket,
                Key=key,
                ExtraArgs={"ContentType": content_type},
            )
        except ClientError as exc:
            if self._is_missing_bucket_error(exc):
                raise S3BucketMissingError(f"S3 bucket does not exist: {bucket}") from exc
            raise S3UploadError(f"Failed to upload {path} to s3://{bucket}/{key}") from exc
        except (BotoCoreError, OSError) as exc:
            raise S3UploadError(f"Failed to upload {path} to s3://{bucket}/{key}") from exc

    @staticmethod
    def _content_type(path: Path) -> str:
        content_type, _encoding = mimetypes.guess_type(path.name)
        return content_type or "application/octet-stream"

    @staticmethod
    def _is_missing_bucket_error(exc: ClientError) -> bool:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchBucket", "NotFound"}

    @staticmethod
    def _key_segment(value: str, name: str) -> str:
        segment = value.strip()
        if not segment:
            raise ValueError(f"{name} must not be empty")
        if "/" in segment or "\\" in segment:
            raise ValueError(f"{name} must be a single object-key segment")
        return segment

    @staticmethod
    def _require_file(local_path: str | Path) -> Path:
        path = Path(local_path)
        if not path.is_file():
            raise S3AssetFileNotFoundError(f"File not found: {path}")
        return path
