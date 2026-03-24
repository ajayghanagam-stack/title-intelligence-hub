"""Cross-tenant isolation tests.

Validates that data belonging to one org is invisible to another org
through the API layer. This is the definitive test for defense-in-depth
tenant scoping (org_id in every WHERE clause).
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser
from app.core.deps import get_db, get_current_member
from app.config import get_settings
from app.models.organization import Organization
from app.models.user import User
from app.models.subscription import Subscription
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk

from tests.conftest import (
    TEST_ORG_ID, TEST_APP_ID, TEST_AUTH_USER_ID, TEST_USER_ID,
    test_session_factory, get_test_settings,
)
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FLAG_ID

# Second org — the "attacker" org that should NOT see org A's data
OTHER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000199")
OTHER_AUTH_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000299")


@pytest_asyncio.fixture
async def cross_tenant_data(db_session: AsyncSession, seed_data):
    """Seed org A's pack data AND create org B with no data."""
    # Org A's pack + data (uses seed_data which creates org A)
    pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Org A Pack", status="completed")
    db_session.add(pack)

    file = PackFile(
        pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        filename="test.pdf", storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        file_size=1024,
    )
    db_session.add(file)

    ext = Extraction(
        pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        extraction_type="party", label="Buyer",
        value={"name": "John Doe"}, evidence_refs=[], confidence=0.9,
    )
    db_session.add(ext)

    flag = Flag(
        id=TEST_FLAG_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        flag_type="unresolved_lien", severity="high",
        title="Outstanding Lien", description="Test flag",
        ai_explanation="Test AI explanation for cross-tenant test",
        evidence_refs=[{"page_number": 1, "text_snippet": "test"}],
    )
    db_session.add(flag)

    chunk = TextChunk(
        pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
        page_number=1, content="Title commitment text for org A",
    )
    db_session.add(chunk)

    # Org B — separate org with subscription but NO packs
    org_b = Organization(id=OTHER_ORG_ID, name="Other Org", slug="other-org")
    db_session.add(org_b)

    user_b = User(
        id=OTHER_USER_ID, auth_user_id=OTHER_AUTH_USER_ID,
        org_id=OTHER_ORG_ID, email="other@example.com",
        full_name="Other User", role="owner",
    )
    db_session.add(user_b)

    sub_b = Subscription(
        org_id=OTHER_ORG_ID, app_id=TEST_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub_b)

    await db_session.commit()
    return {"pack": pack, "user_b": user_b}


@pytest_asyncio.fixture
async def client_org_b(db_session: AsyncSession, cross_tenant_data):
    """HTTP client authenticated as org B (the 'attacker')."""
    from app.core.auth import get_current_user
    from app.main import create_app

    app = create_app(session_factory_override=test_session_factory)

    async def override_db():
        yield db_session

    def override_settings():
        return get_test_settings()

    async def override_current_user():
        return AuthenticatedUser(
            auth_user_id=OTHER_AUTH_USER_ID,
            email="other@example.com",
            org_id=OTHER_ORG_ID,
            role="owner",
        )

    async def override_current_member():
        return cross_tenant_data["user_b"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_member] = override_current_member

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Org-Id": str(OTHER_ORG_ID)},
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_org_b_cannot_list_org_a_packs(client_org_b):
    """Org B should see zero packs (org A's pack is invisible)."""
    resp = await client_org_b.get("/api/v1/apps/title-intelligence/packs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_org_b_cannot_get_org_a_pack(client_org_b):
    """Org B should get 404 when requesting org A's pack by ID."""
    resp = await client_org_b.get(f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_b_cannot_see_org_a_flags(client_org_b):
    """Org B should get 404 when requesting flags for org A's pack."""
    resp = await client_org_b.get(f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags")
    # The flags endpoint may return empty or 404 depending on implementation
    # Either way, org A's flag should not appear
    if resp.status_code == 200:
        data = resp.json()
        flags = data.get("flags", data) if isinstance(data, dict) else data
        assert len(flags) == 0
    else:
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_b_cannot_see_org_a_extractions(client_org_b):
    """Org B should get empty results for org A's pack extractions."""
    resp = await client_org_b.get(f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/extractions")
    if resp.status_code == 200:
        assert resp.json() == []
    else:
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_b_cannot_search_org_a_text(client_org_b):
    """Org B should get empty search results for org A's text chunks."""
    resp = await client_org_b.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/search",
        params={"q": "title commitment"},
    )
    if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 0
    else:
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_b_cannot_review_org_a_flag(client_org_b):
    """Org B should get 404 trying to review org A's flag."""
    resp = await client_org_b.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "approve", "reason_code": "standard_exception", "notes": "hacked"},
    )
    assert resp.status_code == 404
