import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.core.auth import AuthenticatedUser
from app.core.deps import get_db, get_current_member, require_platform_admin
from app.models import Base, ensure_micro_app_models
from app.models.organization import Organization
from app.models.user import User
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription

# Use SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


def get_test_settings():
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        JWT_SECRET="test-secret-key",
        CORS_ORIGINS=["http://localhost:3000"],
        STORAGE_PATH="./test_storage",
    )


test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

# Fixed test IDs
TEST_AUTH_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")
TEST_APP_ID = uuid.UUID("00000000-0000-0000-0000-000000001000")


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

    # Create active subscription for TI so middleware passes
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


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, seed_data):
    from app.config import get_settings
    from app.core.auth import get_current_user
    from app.main import create_app

    # Pass the test session factory to the app so middleware uses test DB
    app = create_app(session_factory_override=test_session_factory)

    # Override dependencies
    async def override_db():
        yield db_session

    def override_settings():
        return get_test_settings()

    async def override_current_user():
        return AuthenticatedUser(
            auth_user_id=TEST_AUTH_USER_ID,
            email="test@example.com",
            org_id=TEST_ORG_ID,
            role="owner",
        )

    async def override_current_member():
        return seed_data["user"]

    async def override_platform_admin():
        return seed_data["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_member] = override_current_member
    app.dependency_overrides[require_platform_admin] = override_platform_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
