"""Tests for batch text chunk insertion in _create_text_chunks_from_transcriptions."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk
from app.micro_apps.title_intelligence.pipeline.stages import _create_text_chunks_from_transcriptions

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


@pytest_asyncio.fixture
async def pack_for_chunks(db_session: AsyncSession, seed_data):
    """Create a minimal pack for text chunk tests."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Chunk Test Pack",
        status="completed",
    )
    db_session.add(pack)
    await db_session.commit()
    return pack


class TestBatchTextChunks:
    """Test _create_text_chunks_from_transcriptions batch insertion."""

    @pytest.mark.asyncio
    async def test_correct_count(self, db_session: AsyncSession, pack_for_chunks):
        """Verify chunk count matches expected output."""
        transcriptions = [
            {"page_number": 1, "text": "A" * 600},  # Should produce >=2 chunks (500 + overlap)
            {"page_number": 2, "text": "B" * 300},  # 1 chunk
        ]
        await _create_text_chunks_from_transcriptions(
            db_session, TEST_ORG_ID, TEST_PACK_ID, transcriptions,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TextChunk).where(
                TextChunk.pack_id == TEST_PACK_ID,
                TextChunk.org_id == TEST_ORG_ID,
            )
        )
        chunks = list(result.scalars().all())
        assert len(chunks) >= 3  # At least 2 from page 1 + 1 from page 2

    @pytest.mark.asyncio
    async def test_empty_input(self, db_session: AsyncSession, pack_for_chunks):
        """Empty transcriptions → 0 chunks."""
        await _create_text_chunks_from_transcriptions(
            db_session, TEST_ORG_ID, TEST_PACK_ID, [],
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TextChunk).where(
                TextChunk.pack_id == TEST_PACK_ID,
                TextChunk.org_id == TEST_ORG_ID,
            )
        )
        chunks = list(result.scalars().all())
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_skip_short_chunks(self, db_session: AsyncSession, pack_for_chunks):
        """Chunks shorter than 10 chars (stripped) should be filtered."""
        transcriptions = [
            {"page_number": 1, "text": "short"},  # <10 chars → should be skipped
            {"page_number": 2, "text": "This is a sufficiently long text to be kept as a chunk."},
        ]
        await _create_text_chunks_from_transcriptions(
            db_session, TEST_ORG_ID, TEST_PACK_ID, transcriptions,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TextChunk).where(
                TextChunk.pack_id == TEST_PACK_ID,
                TextChunk.org_id == TEST_ORG_ID,
            )
        )
        chunks = list(result.scalars().all())
        # "short" is 5 chars → skipped; long text → at least 1 chunk
        assert len(chunks) >= 1
        assert all(len(c.content.strip()) >= 10 for c in chunks)

    @pytest.mark.asyncio
    async def test_skip_empty_text(self, db_session: AsyncSession, pack_for_chunks):
        """Transcriptions with empty text should produce no chunks."""
        transcriptions = [
            {"page_number": 1, "text": ""},
            {"page_number": 2, "text": None},
        ]
        await _create_text_chunks_from_transcriptions(
            db_session, TEST_ORG_ID, TEST_PACK_ID, transcriptions,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TextChunk).where(
                TextChunk.pack_id == TEST_PACK_ID,
                TextChunk.org_id == TEST_ORG_ID,
            )
        )
        chunks = list(result.scalars().all())
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_deterministic_3x(self, db_session: AsyncSession, pack_for_chunks):
        """3x same input → identical chunk content."""
        transcriptions = [
            {"page_number": 1, "text": "Alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu."},
            {"page_number": 2, "text": "The quick brown fox jumps over the lazy dog. " * 10},
        ]

        all_runs: list[list[str]] = []
        for _ in range(3):
            # Clear chunks from previous run
            from sqlalchemy import delete
            await db_session.execute(
                delete(TextChunk).where(
                    TextChunk.pack_id == TEST_PACK_ID,
                    TextChunk.org_id == TEST_ORG_ID,
                )
            )
            await db_session.commit()

            await _create_text_chunks_from_transcriptions(
                db_session, TEST_ORG_ID, TEST_PACK_ID, transcriptions,
            )
            await db_session.commit()

            result = await db_session.execute(
                select(TextChunk).where(
                    TextChunk.pack_id == TEST_PACK_ID,
                    TextChunk.org_id == TEST_ORG_ID,
                ).order_by(TextChunk.page_number)
            )
            chunks = list(result.scalars().all())
            all_runs.append([c.content for c in chunks])

        # All runs should produce identical chunks
        assert all_runs[0] == all_runs[1]
        assert all_runs[1] == all_runs[2]

    @pytest.mark.asyncio
    async def test_page_numbers_preserved(self, db_session: AsyncSession, pack_for_chunks):
        """Each chunk should have the correct page_number from its source transcription."""
        transcriptions = [
            {"page_number": 5, "text": "Content for page five which is long enough to create a chunk."},
            {"page_number": 12, "text": "Content for page twelve also long enough to create a chunk."},
        ]
        await _create_text_chunks_from_transcriptions(
            db_session, TEST_ORG_ID, TEST_PACK_ID, transcriptions,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TextChunk).where(
                TextChunk.pack_id == TEST_PACK_ID,
                TextChunk.org_id == TEST_ORG_ID,
            )
        )
        chunks = list(result.scalars().all())
        page_numbers = {c.page_number for c in chunks}
        assert page_numbers == {5, 12}
