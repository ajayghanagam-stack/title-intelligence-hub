import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID
from app.micro_apps.title_intelligence.models.chat_message import ChatMessage


@pytest.mark.asyncio
async def test_chat_history_empty(client: AsyncClient, sample_pack):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/chat",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.asyncio
async def test_chat_history_with_messages(client: AsyncClient, sample_pack, db_session: AsyncSession):
    """Pre-seeded chat messages appear in history."""
    msg1 = ChatMessage(
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        role="user",
        content="Who is the buyer?",
    )
    msg2 = ChatMessage(
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        role="assistant",
        content="The buyer is John Doe.",
        citations=[{"page_number": 1, "text_snippet": "Buyer: John Doe"}],
    )
    db_session.add(msg1)
    db_session.add(msg2)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/chat",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["role"] == "user"
    assert data[0]["content"] == "Who is the buyer?"
    assert data[1]["role"] == "assistant"
    assert data[1]["citations"] is not None
    assert len(data[1]["citations"]) == 1
