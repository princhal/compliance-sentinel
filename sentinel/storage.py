"""Blob storage for raw regulation files and PDF reports: local disk or any S3-compatible store."""

from __future__ import annotations

from pathlib import Path

from sentinel.config import Settings, get_settings


class Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._s3 = None
        if self.settings.storage_backend == "s3":
            import boto3  # Reads AWS_ENDPOINT_URL_S3 and keys from the environment (Tigris on Fly).

            self._s3 = boto3.client("s3")

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self._s3 is not None:
            self._s3.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=data,
                                ContentType=content_type)
            return f"s3://{self.settings.s3_bucket}/{key}"
        path = self.settings.data_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get(self, ref: str) -> bytes:
        if ref.startswith("s3://"):
            assert self._s3 is not None, "S3 reference but STORAGE_BACKEND is not s3"
            bucket, _, key = ref[5:].partition("/")
            return self._s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return Path(ref).read_bytes()
