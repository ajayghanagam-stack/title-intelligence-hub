"""Benchmark-specific fixtures.

Provides its own db_session and seed_data (mirroring tests/conftest.py)
plus benchmark-specific fixtures for packs, mocked examiner results,
and version metadata.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.models import Base, ensure_micro_app_models
from app.models.organization import Organization
from app.models.user import User
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerBatchResult,
    ExaminerConsolidatedResult,
    ExaminerExtraction,
    ExaminerFlag,
    ExaminerSection,
    PageTranscription,
)

# Ensure PIPELINE_MODE env var is valid
os.environ.setdefault("PIPELINE_MODE", "legacy")
if os.environ.get("PIPELINE_MODE") not in ("native_pdf", "legacy"):
    os.environ["PIPELINE_MODE"] = "legacy"
get_settings.cache_clear()

# Reuse the same test database as tests/conftest.py
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

# Shared test IDs (same as tests/conftest.py)
TEST_AUTH_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")
TEST_APP_ID = uuid.UUID("00000000-0000-0000-0000-000000001000")

# Fixed benchmark IDs
BENCH_PACK_ID = uuid.UUID("00000000-0000-0000-0000-0000000b0001")
BENCH_FILE_ID = uuid.UUID("00000000-0000-0000-0000-0000000b0002")
BENCH_PIPELINE_RUN_ID = uuid.UUID("00000000-0000-0000-0000-0000000b0003")


# ---------------------------------------------------------------------------
# DB session + seed data fixtures (mirrors tests/conftest.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    ensure_micro_app_models()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    org = Organization(id=TEST_ORG_ID, name="Test Org", slug="test-org")
    db_session.add(org)

    user = User(
        id=TEST_USER_ID,
        auth_user_id=TEST_AUTH_USER_ID,
        org_id=TEST_ORG_ID,
        email="test@example.com",
        full_name="Test User",
        role="owner",
    )
    db_session.add(user)

    micro_app = MicroApp(
        id=TEST_APP_ID,
        name="Title Intelligence",
        slug="title-intelligence",
        description="AI-powered title analysis",
        icon="file-search",
    )
    db_session.add(micro_app)

    sub = Subscription(
        org_id=TEST_ORG_ID,
        app_id=TEST_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)

    await db_session.commit()
    return {"org": org, "user": user, "micro_app": micro_app}


# ---------------------------------------------------------------------------
# Benchmark-specific fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def benchmark_pack_factory(db_session: AsyncSession, seed_data):
    """Factory fixture: ``await factory(page_count)`` -> Pack with N pages."""

    async def _create(page_count: int) -> Pack:
        pack = Pack(
            id=BENCH_PACK_ID,
            org_id=TEST_ORG_ID,
            name=f"Benchmark Pack ({page_count}pp)",
            status="processing",
        )
        db_session.add(pack)

        pack_file = PackFile(
            id=BENCH_FILE_ID,
            pack_id=BENCH_PACK_ID,
            org_id=TEST_ORG_ID,
            filename="benchmark.pdf",
            storage_path=f"{TEST_ORG_ID}/{BENCH_PACK_ID}/files/benchmark.pdf",
            file_size=page_count * 5000,
            content_hash="bench" + "0" * 60,
            page_count=page_count,
        )
        db_session.add(pack_file)

        for i in range(1, page_count + 1):
            page = Page(
                pack_id=BENCH_PACK_ID,
                org_id=TEST_ORG_ID,
                file_id=BENCH_FILE_ID,
                page_number=i,
                ocr_text=f"Sample OCR text for page {i}.",
            )
            db_session.add(page)

        await db_session.commit()
        return pack

    return _create


# ---------------------------------------------------------------------------
# Helper builders (not fixtures — used directly by tests)
# ---------------------------------------------------------------------------


def build_mock_examiner_result(page_count: int) -> ExaminerConsolidatedResult:
    """Build a realistic ExaminerConsolidatedResult scaled to *page_count*."""
    transcriptions = [
        PageTranscription(page_number=i, text=f"Transcribed text for page {i}")
        for i in range(1, page_count + 1)
    ]

    sections = [
        ExaminerSection(section_type="schedule_a", start_page=1, end_page=max(1, page_count // 6), confidence=0.95),
        ExaminerSection(section_type="schedule_b1", start_page=max(2, page_count // 6 + 1), end_page=max(3, page_count // 3), confidence=0.92),
        ExaminerSection(section_type="schedule_b2", start_page=max(4, page_count // 3 + 1), end_page=max(5, page_count * 3 // 4), confidence=0.90),
        ExaminerSection(section_type="endorsements", start_page=max(6, page_count * 3 // 4 + 1), end_page=page_count, confidence=0.88),
    ]

    extractions = [
        ExaminerExtraction(
            extraction_type="party",
            label="Buyer: Jane Smith",
            value={"name": "Jane Smith", "role": "buyer"},
            evidence_refs=[{"page_number": 1, "text_snippet": "Buyer: Jane Smith"}],
            confidence=0.95,
        ),
        ExaminerExtraction(
            extraction_type="property",
            label="Property Address",
            value={"address": "1234 Oakridge Dr", "city": "Springfield", "state": "IL"},
            evidence_refs=[{"page_number": 1, "text_snippet": "1234 Oakridge Dr"}],
            confidence=0.97,
        ),
        ExaminerExtraction(
            extraction_type="requirement",
            label="Requirement 1: Pay off existing mortgage",
            value={"description": "Pay off existing mortgage balance"},
            evidence_refs=[{"page_number": 3, "text_snippet": "Pay off mortgage"}],
            confidence=0.92,
        ),
    ]

    flags = [
        ExaminerFlag(
            flag_type="unresolved_lien",
            severity="high",
            title="Outstanding Deed of Trust",
            description="Deed of trust not reconveyed",
            ai_explanation="Found deed of trust without reconveyance",
            evidence_refs=[{"page_number": 5, "text_snippet": "Deed of Trust"}],
        ),
    ]

    return ExaminerConsolidatedResult(
        page_transcriptions=transcriptions,
        sections=sections,
        extractions=extractions,
        flags=flags,
        rate_limit_hits=0,
        total_retries=0,
    )


def build_mock_stage_timings(page_count: int) -> dict[str, float]:
    """Return realistic stage timings (within SLA) for *page_count* pages."""
    factor = page_count / 25.0
    return {
        "ingest": round(0.5 * factor, 2),
        "render": round(0.3 * factor, 2),
        "examine": round(8.0 * (factor ** 0.7), 2),
        "complete": round(0.4 * factor, 2),
    }


def build_mock_version_metadata(page_count: int) -> dict:
    """Build version_metadata dict matching what the orchestrator writes."""
    timings = build_mock_stage_timings(page_count)
    batch_size = 20
    num_batches = max(1, (page_count + batch_size - 1) // batch_size)
    input_per_batch = page_count * 300 // num_batches
    output_per_batch = page_count * 100 // num_batches

    batch_results = [
        {
            "input_tokens": input_per_batch,
            "output_tokens": output_per_batch,
            "llm_elapsed_seconds": timings["examine"] / num_batches,
        }
        for _ in range(num_batches)
    ]

    return {
        "stage_timings": timings,
        "total_elapsed_seconds": round(sum(timings.values()), 2),
        "batch_results": batch_results,
        "total_tokens": page_count * 400,
        "rate_limit_hits": 0,
        "pipeline_mode": "native_pdf",
    }
