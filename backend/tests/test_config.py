"""Tests for config validation."""

import pytest
from app.config import Settings


def test_jwt_secret_rejected_in_non_debug():
    """Insecure default JWT secret is rejected when DEBUG is not set."""
    with pytest.raises(ValueError, match="CRITICAL.*JWT_SECRET"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="change-me-in-production",
            DEBUG=False,
        )


def test_jwt_secret_allowed_in_debug():
    """Insecure default JWT secret is allowed when DEBUG=True."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="change-me-in-production",
        DEBUG=True,
    )
    assert settings.JWT_SECRET == "change-me-in-production"


def test_custom_jwt_secret_accepted():
    """Custom JWT secret is always accepted."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="my-strong-secret-key",
        DEBUG=False,
    )
    assert settings.JWT_SECRET == "my-strong-secret-key"


def test_invalid_storage_provider_rejected():
    """Invalid STORAGE_PROVIDER value is rejected by Literal type."""
    with pytest.raises(Exception):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-key",
            STORAGE_PROVIDER="invalid",
        )


def test_invalid_pipeline_backend_rejected():
    """Invalid PIPELINE_BACKEND value is rejected by Literal type."""
    with pytest.raises(Exception):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-key",
            PIPELINE_BACKEND="celery",
        )
