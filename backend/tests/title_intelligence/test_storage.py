"""Tests for storage provider abstraction."""

import uuid
import pytest
import pytest_asyncio
import tempfile
import shutil
from pathlib import Path

from app.micro_apps.title_intelligence.services.storage import (
    LocalStorage,
    StorageProvider,
    get_storage,
)


@pytest_asyncio.fixture
async def local_storage():
    """Create a LocalStorage with a temporary directory."""
    tmpdir = tempfile.mkdtemp()
    storage = LocalStorage(base_path=tmpdir)
    yield storage
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_local_storage_put_get(local_storage: LocalStorage):
    """Test writing and reading a file."""
    data = b"hello world"
    await local_storage.put_object("test/file.txt", data)
    result = await local_storage.get_object("test/file.txt")
    assert result == data


@pytest.mark.asyncio
async def test_local_storage_exists(local_storage: LocalStorage):
    """Test file existence check."""
    assert not await local_storage.exists("nonexistent.txt")
    await local_storage.put_object("exists.txt", b"data")
    assert await local_storage.exists("exists.txt")


@pytest.mark.asyncio
async def test_local_storage_delete(local_storage: LocalStorage):
    """Test file deletion."""
    await local_storage.put_object("to_delete.txt", b"data")
    assert await local_storage.exists("to_delete.txt")
    await local_storage.delete_object("to_delete.txt")
    assert not await local_storage.exists("to_delete.txt")


@pytest.mark.asyncio
async def test_local_storage_delete_dir(local_storage: LocalStorage):
    """Test directory deletion."""
    await local_storage.put_object("dir/file1.txt", b"data1")
    await local_storage.put_object("dir/file2.txt", b"data2")
    assert await local_storage.exists("dir/file1.txt")
    await local_storage.delete_dir("dir")
    assert not await local_storage.exists("dir/file1.txt")
    assert not await local_storage.exists("dir/file2.txt")


@pytest.mark.asyncio
async def test_backward_compatible_methods(local_storage: LocalStorage):
    """Test that save/read aliases work."""
    rel_path = await local_storage.save("compat/test.txt", b"compat data")
    assert rel_path == "compat/test.txt"
    data = await local_storage.read("compat/test.txt")
    assert data == b"compat data"


def test_path_builders(local_storage: LocalStorage):
    """Test path builder methods."""
    org_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    pack_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    assert local_storage.make_pack_path(org_id, pack_id, "doc.pdf") == f"{org_id}/{pack_id}/files/doc.pdf"
    assert local_storage.make_page_path(org_id, pack_id, 1) == f"{org_id}/{pack_id}/pages/page_0001.jpg"
    assert local_storage.make_thumb_path(org_id, pack_id, 1) == f"{org_id}/{pack_id}/thumbs/page_0001.jpg"
    assert local_storage.make_ocr_path(org_id, pack_id, 1) == f"{org_id}/{pack_id}/ocr/page_0001.json"
    assert local_storage.make_report_path(org_id, pack_id, "report.pdf") == f"{org_id}/{pack_id}/reports/report.pdf"


def test_ai_cache_path(local_storage: LocalStorage):
    """AI cache path is org-scoped (not pack-scoped) so same file in different packs hits cache."""
    org_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    pack_id_a = uuid.UUID("22222222-2222-2222-2222-222222222222")
    pack_id_b = uuid.UUID("33333333-3333-3333-3333-333333333333")
    hash_v1 = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    hash_v2 = "9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba"

    path_ing = local_storage.make_ai_cache_path(org_id, pack_id_a, "ingestion", hash_v1)
    path_risk = local_storage.make_ai_cache_path(org_id, pack_id_a, "risk", hash_v1)
    path_diff = local_storage.make_ai_cache_path(org_id, pack_id_a, "ingestion", hash_v2)

    # Contains stage and version segment
    assert "/ai_cache/ingestion/v_abcdef123456" in path_ing
    assert "/ai_cache/risk/v_abcdef123456" in path_risk
    assert path_ing.endswith(".json")

    # Path is org-scoped, NOT pack-scoped — no pack_id in path
    assert str(pack_id_a) not in path_ing

    # Different pack_ids with same hash produce the SAME path (cross-pack cache hit)
    assert path_ing == local_storage.make_ai_cache_path(org_id, pack_id_b, "ingestion", hash_v1)

    # Different stages produce different paths
    assert path_ing != path_risk

    # Different hashes produce different paths
    assert path_ing != path_diff

    # Same inputs produce same path (deterministic)
    assert path_ing == local_storage.make_ai_cache_path(org_id, pack_id_a, "ingestion", hash_v1)


def test_ocr_path_versioned(local_storage: LocalStorage):
    """Versioned OCR path includes version segment and changes with hash."""
    org_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    pack_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    hash_v1 = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    hash_v2 = "9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba"

    path_v1 = local_storage.make_ocr_path_versioned(org_id, pack_id, 1, hash_v1)
    path_v2 = local_storage.make_ocr_path_versioned(org_id, pack_id, 1, hash_v2)

    # Contains version segment
    assert "/ocr/v_abcdef12/" in path_v1
    assert "/ocr/v_98765432/" in path_v2

    # Different hashes produce different paths
    assert path_v1 != path_v2

    # Same hash produces same path (deterministic)
    assert path_v1 == local_storage.make_ocr_path_versioned(org_id, pack_id, 1, hash_v1)

    # Ends with expected filename
    assert path_v1.endswith("page_0001.json")


@pytest.mark.asyncio
async def test_local_storage_presign_url(local_storage: LocalStorage):
    """Local storage presign_url returns absolute path."""
    await local_storage.put_object("presign.txt", b"data")
    url = await local_storage.presign_url("presign.txt")
    assert "presign.txt" in url


def test_storage_provider_is_abstract():
    """StorageProvider cannot be instantiated directly."""
    with pytest.raises(TypeError):
        StorageProvider()


@pytest.mark.asyncio
async def test_content_type_ignored_for_local(local_storage: LocalStorage):
    """Local storage ignores content_type parameter."""
    await local_storage.put_object("typed.pdf", b"pdf data", content_type="application/pdf")
    result = await local_storage.get_object("typed.pdf")
    assert result == b"pdf data"


@pytest.mark.asyncio
async def test_path_traversal_blocked(local_storage: LocalStorage):
    """Path traversal attempts should raise ValueError."""
    with pytest.raises(ValueError, match="Path traversal detected"):
        await local_storage.put_object("../../etc/passwd", b"malicious")

    with pytest.raises(ValueError, match="Path traversal detected"):
        await local_storage.get_object("../../../etc/shadow")

    with pytest.raises(ValueError, match="Path traversal detected"):
        await local_storage.delete_object("foo/../../bar")
