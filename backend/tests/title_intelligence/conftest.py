import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk
from app.micro_apps.title_intelligence.models.chat_message import ChatMessage
from app.models.subscription import Subscription

from tests.conftest import TEST_ORG_ID, TEST_USER_ID, TEST_APP_ID

TEST_PACK_ID = uuid.UUID("00000000-0000-0000-0000-000000010000")
TEST_FILE_ID = uuid.UUID("00000000-0000-0000-0000-000000020000")
TEST_FLAG_ID = uuid.UUID("00000000-0000-0000-0000-000000030000")


@pytest_asyncio.fixture
async def ti_subscription(db_session: AsyncSession, seed_data):
    """Create an active subscription for TI."""
    sub = Subscription(
        org_id=TEST_ORG_ID,
        app_id=TEST_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


@pytest_asyncio.fixture
async def sample_pack(db_session: AsyncSession, seed_data):
    """Create a sample pack."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Title Pack",
        status="completed",
    )
    db_session.add(pack)
    await db_session.commit()
    return pack


@pytest_asyncio.fixture
async def sample_pack_with_data(db_session: AsyncSession, sample_pack):
    """Create a sample pack with extractions and flags."""
    # Add extraction
    ext = Extraction(
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        extraction_type="party",
        label="Buyer",
        value={"name": "John Doe", "role": "buyer"},
        evidence_refs=[{"page_number": 1, "text_snippet": "Buyer: John Doe"}],
        confidence=0.95,
    )
    db_session.add(ext)

    # Add flag
    flag = Flag(
        id=TEST_FLAG_ID,
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        flag_type="unresolved_lien",
        severity="high",
        title="Outstanding Deed of Trust",
        description="A deed of trust was found that has not been reconveyed.",
        ai_explanation="The deed of trust recorded on 2020-01-15 shows no corresponding reconveyance.",
        evidence_refs=[{"page_number": 5, "text_snippet": "Deed of Trust dated 2020-01-15"}],
    )
    db_session.add(flag)

    # Add text chunks
    chunk = TextChunk(
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        page_number=1,
        content="This is a sample text chunk from the title document.",
    )
    db_session.add(chunk)

    await db_session.commit()
    return sample_pack
