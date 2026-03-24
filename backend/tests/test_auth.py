"""Auth endpoint tests including rate limiting."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import hash_password
from app.models.user import User
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, TEST_AUTH_USER_ID


@pytest_asyncio.fixture
async def user_with_password(db_session: AsyncSession, seed_data):
    """Update the test user with a password hash for login tests."""
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == TEST_USER_ID))
    user = result.scalar_one()
    user.password_hash = hash_password("test-password-123")
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, user_with_password):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "test-password-123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, user_with_password):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit(client: AsyncClient, user_with_password):
    """6th login attempt within a minute should return 429."""
    for i in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrong-password"},
        )

    # 6th attempt should be rate limited
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 429
