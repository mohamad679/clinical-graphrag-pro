"""
Storage abstraction supporting local disk for development and S3-compatible object storage for production.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StoredObject:
    provider: str
    bucket: str
    object_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum: str
    encryption_status: str
    storage_metadata: dict


class StorageBackend(Protocol):
    async def store_bytes(
        self,
        *,
        content: bytes,
        object_key: str,
        original_filename: str,
        content_type: str,
    ) -> StoredObject: ...

    async def read_bytes(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> bytes: ...

    async def delete(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> None: ...

    def resolve_local_path(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> Path | None: ...


class LocalStorageBackend:
    def __init__(self):
        settings = get_settings()
        self._root = settings.upload_dir
        self._bucket = settings.storage_bucket or "local"
        self._root.mkdir(parents=True, exist_ok=True)

    async def store_bytes(
        self,
        *,
        content: bytes,
        object_key: str,
        original_filename: str,
        content_type: str,
    ) -> StoredObject:
        path = self._root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(
            provider="local",
            bucket=self._bucket,
            object_key=object_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
            checksum=hashlib.sha256(content).hexdigest(),
            encryption_status="not_encrypted",
            storage_metadata={"local_path": str(path)},
        )

    async def read_bytes(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> bytes:
        path = self.resolve_local_path(bucket=bucket, object_key=object_key, storage_metadata=storage_metadata)
        if path is None or not path.exists():
            raise FileNotFoundError(f"Local storage object not found: {object_key}")
        return path.read_bytes()

    async def delete(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> None:
        path = self.resolve_local_path(bucket=bucket, object_key=object_key, storage_metadata=storage_metadata)
        if path and path.exists():
            path.unlink()

    def resolve_local_path(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> Path | None:
        if storage_metadata and storage_metadata.get("local_path"):
            return Path(str(storage_metadata["local_path"]))
        return self._root / object_key


class S3StorageBackend:
    def __init__(self):
        settings = get_settings()
        self._bucket = settings.storage_bucket
        self._endpoint_url = settings.storage_endpoint_url or None
        self._region = settings.storage_region or None
        self._access_key = settings.storage_access_key or None
        self._secret_key = settings.storage_secret_key or None
        self._use_ssl = settings.storage_use_ssl
        self._encrypt_uploads = settings.storage_encrypt_uploads
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "boto3 is required for STORAGE_PROVIDER=s3 or minio-style object storage."
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            use_ssl=self._use_ssl,
        )
        return self._client

    async def store_bytes(
        self,
        *,
        content: bytes,
        object_key: str,
        original_filename: str,
        content_type: str,
    ) -> StoredObject:
        client = self._get_client()

        def _upload() -> None:
            extra_args = {"ContentType": content_type}
            if self._encrypt_uploads:
                extra_args["ServerSideEncryption"] = "AES256"
            client.put_object(Bucket=self._bucket, Key=object_key, Body=content, **extra_args)

        await asyncio.to_thread(_upload)
        return StoredObject(
            provider="s3",
            bucket=self._bucket,
            object_key=object_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
            checksum=hashlib.sha256(content).hexdigest(),
            encryption_status="encrypted" if self._encrypt_uploads else "not_encrypted",
            storage_metadata={"endpoint_url": self._endpoint_url, "region": self._region},
        )

    async def read_bytes(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> bytes:
        client = self._get_client()

        def _download() -> bytes:
            response = client.get_object(Bucket=bucket, Key=object_key)
            return response["Body"].read()

        return await asyncio.to_thread(_download)

    async def delete(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> None:
        client = self._get_client()
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=object_key)

    def resolve_local_path(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> Path | None:
        return None


class StorageService:
    """Facade used by document/image flows."""

    def __init__(self):
        self._backend: StorageBackend | None = None
        self._settings = get_settings()

    def _get_backend(self) -> StorageBackend:
        if self._backend is not None:
            return self._backend

        provider = self._settings.storage_provider.strip().lower()
        if provider in {"s3", "minio"}:
            self._backend = S3StorageBackend()
        else:
            self._backend = LocalStorageBackend()
        return self._backend

    def build_object_key(self, *, category: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        prefix_parts = [self._settings.storage_prefix.strip("/"), category.strip("/")]
        prefix = "/".join(part for part in prefix_parts if part)
        generated = f"{uuid.uuid4().hex}{suffix}"
        return f"{prefix}/{generated}" if prefix else generated

    async def store_bytes(
        self,
        *,
        category: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        object_key: str | None = None,
    ) -> StoredObject:
        resolved_content_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        key = object_key or self.build_object_key(category=category, filename=filename)
        return await self._get_backend().store_bytes(
            content=content,
            object_key=key,
            original_filename=filename,
            content_type=resolved_content_type,
        )

    async def read_bytes(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> bytes:
        return await self._get_backend().read_bytes(
            bucket=bucket,
            object_key=object_key,
            storage_metadata=storage_metadata,
        )

    async def delete(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> None:
        await self._get_backend().delete(
            bucket=bucket,
            object_key=object_key,
            storage_metadata=storage_metadata,
        )

    def resolve_local_path(self, *, bucket: str, object_key: str, storage_metadata: dict | None = None) -> Path | None:
        return self._get_backend().resolve_local_path(
            bucket=bucket,
            object_key=object_key,
            storage_metadata=storage_metadata,
        )


storage_service = StorageService()
