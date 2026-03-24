"""Pluggable storage provider abstraction.

Platform-level service supporting local filesystem and S3/MinIO.
Factory function selects provider based on STORAGE_PROVIDER setting.
"""

import uuid
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings

logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """Abstract storage provider interface."""

    @abstractmethod
    async def get_object(self, key: str) -> bytes:
        """Read an object by key."""
        ...

    @abstractmethod
    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Write an object."""
        ...

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        """Delete an object."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if an object exists."""
        ...

    @abstractmethod
    async def presign_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a pre-signed URL for direct access."""
        ...

    # Backward-compatible aliases
    async def save(self, rel_path: str, data: bytes) -> str:
        await self.put_object(rel_path, data)
        return rel_path

    async def read(self, rel_path: str) -> bytes:
        return await self.get_object(rel_path)

    async def delete(self, rel_path: str) -> None:
        await self.delete_object(rel_path)

    # Path builders (shared across all providers)
    def make_pack_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, filename: str) -> str:
        return f"{org_id}/{pack_id}/files/{filename}"

    def make_page_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, page_num: int, suffix: str = ".jpg") -> str:
        return f"{org_id}/{pack_id}/pages/page_{page_num:04d}{suffix}"

    def make_thumb_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, page_num: int) -> str:
        return f"{org_id}/{pack_id}/thumbs/page_{page_num:04d}.jpg"

    def make_ocr_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, page_num: int) -> str:
        return f"{org_id}/{pack_id}/ocr/page_{page_num:04d}.json"

    def make_ocr_path_versioned(
        self, org_id: uuid.UUID, pack_id: uuid.UUID, page_num: int, version_hash: str
    ) -> str:
        """OCR cache path with version segment. Different engine version → cache miss."""
        return f"{org_id}/{pack_id}/ocr/v_{version_hash[:8]}/page_{page_num:04d}.json"

    def make_ai_cache_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, stage: str, version_hash: str) -> str:
        """AI output cache path keyed by stage and version hash.

        Org-scoped (not pack-scoped) so the same file uploaded to different packs
        gets a cache hit. The version_hash already encodes file content + model +
        prompt + tool schema, making it unique per input combination.
        """
        return f"{org_id}/ai_cache/{stage}/v_{version_hash[:12]}.json"

    def make_report_path(self, org_id: uuid.UUID, pack_id: uuid.UUID, filename: str) -> str:
        return f"{org_id}/{pack_id}/reports/{filename}"


class LocalStorage(StorageProvider):
    """Local filesystem storage provider."""

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or get_settings().STORAGE_PATH)

    def _resolve(self, rel_path: str) -> Path:
        resolved = (self.base_path / rel_path).resolve()
        if not resolved.is_relative_to(self.base_path.resolve()):
            raise ValueError(f"Path traversal detected: {rel_path}")
        return resolved

    async def get_object(self, key: str) -> bytes:
        async with aiofiles.open(self._resolve(key), "rb") as f:
            return await f.read()

    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        full = self._resolve(key)
        full.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full, "wb") as f:
            await f.write(data)

    async def delete_object(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    async def exists(self, key: str) -> bool:
        import aiofiles.os
        return await aiofiles.os.path.exists(self._resolve(key))

    async def presign_url(self, key: str, expires_in: int = 3600) -> str:
        # Local storage returns the absolute file path as URL
        return str(self._resolve(key))

    async def delete_dir(self, rel_path: str) -> None:
        import shutil
        path = self._resolve(rel_path)
        if path.exists():
            shutil.rmtree(path)

    def abs_path(self, rel_path: str) -> str:
        return str(self._resolve(rel_path))


class S3Storage(StorageProvider):
    """S3/MinIO storage provider using aiobotocore for async operations."""

    def __init__(
        self,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
    ):
        settings = get_settings()
        self.endpoint = endpoint or settings.S3_ENDPOINT
        self.bucket = bucket or settings.S3_BUCKET
        self.access_key = access_key or settings.S3_ACCESS_KEY
        self.secret_key = secret_key or settings.S3_SECRET_KEY
        self.region = region or settings.S3_REGION
        self._session = None

    def _get_session(self):
        if self._session is None:
            from aiobotocore.session import AioSession
            self._session = AioSession()
        return self._session

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": self.access_key,
            "aws_secret_access_key": self.secret_key,
        }
        if self.endpoint:
            kwargs["endpoint_url"] = self.endpoint
        if self.region:
            kwargs["region_name"] = self.region
        return kwargs

    async def get_object(self, key: str) -> bytes:
        session = self._get_session()
        async with session.create_client(**self._client_kwargs()) as client:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()

    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        session = self._get_session()
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        async with session.create_client(**self._client_kwargs()) as client:
            await client.put_object(**kwargs)

    async def delete_object(self, key: str) -> None:
        session = self._get_session()
        async with session.create_client(**self._client_kwargs()) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        session = self._get_session()
        async with session.create_client(**self._client_kwargs()) as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
                return True
            except client.exceptions.ClientError:
                return False
            except Exception:
                return False

    async def presign_url(self, key: str, expires_in: int = 3600) -> str:
        session = self._get_session()
        async with session.create_client(**self._client_kwargs()) as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

    async def delete_dir(self, prefix: str) -> None:
        """Delete all objects with the given prefix."""
        session = self._get_session()
        async with session.create_client(**self._client_kwargs()) as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                objects = page.get("Contents", [])
                if objects:
                    delete_objs = [{"Key": obj["Key"]} for obj in objects]
                    await client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": delete_objs},
                    )


def get_storage() -> StorageProvider:
    """Factory function — selects storage provider based on STORAGE_PROVIDER setting."""
    settings = get_settings()
    provider = settings.STORAGE_PROVIDER.lower()

    if provider == "s3":
        logger.info(f"Using S3 storage (endpoint={settings.S3_ENDPOINT}, bucket={settings.S3_BUCKET})")
        return S3Storage()
    else:
        logger.info(f"Using local storage (path={settings.STORAGE_PATH})")
        return LocalStorage()
