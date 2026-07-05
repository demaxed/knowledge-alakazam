# Task 5: S3/MinIO Asset Store

Implement the S3-compatible asset layer.

Add `app/s3_assets.py`.

Requirements:

1. Class `S3AssetStore`.

2. Methods:

   * `ensure_buckets()`
   * `upload_raw_document(local_path, tenant_id, source_id) -> RawUploadResult`
   * `upload_output_tree(local_output_root, tenant_id, source_id) -> list[AssetUploadResult]`
   * `public_asset_url(bucket, key) -> str`
   * `download_raw_document(bucket, key, destination_path)`

3. Preserve relative paths:

   * local `/data/output/{tenant_id}/{source_id}/images/fig1.png`
   * object key `output/{tenant_id}/{source_id}/images/fig1.png`

4. Content-Type detection via `mimetypes`.

5. Error handling:

   * file not found
   * missing bucket
   * upload failed

6. Tests:

   * unit tests for key mapping
   * no real S3 required for unit tests
   * integration test may be skipped unless env is enabled

Acceptance criteria:

* No hardcoded bucket names.
* Public URL builds correctly.
* Key mapping is deterministic.
* `uv run ruff check .` passes.
* `uv run pytest` passes.