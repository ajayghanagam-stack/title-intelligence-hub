"""Tests for dual-model AI provider switching (Gemini ↔ Claude).

Verifies config-driven provider selection, model string resolution,
pipeline mode coercion, version tracking, cache key isolation,
and examiner batch config.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

from app.config import Settings


# ---------------------------------------------------------------------------
# Config: AI_PROVIDER defaults and model resolution
# ---------------------------------------------------------------------------


def test_default_provider_is_gemini():
    """Default AI_PROVIDER is 'gemini'."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
    )
    assert settings.AI_PROVIDER == "gemini"


def test_claude_provider_config():
    """AI_PROVIDER='claude' is accepted."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert settings.AI_PROVIDER == "claude"
    assert settings.ANTHROPIC_API_KEY == "sk-ant-test"


def test_claude_coerces_pipeline_mode_to_legacy():
    """When AI_PROVIDER='claude', PIPELINE_MODE is forced to 'legacy'."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        PIPELINE_MODE="native_pdf",
    )
    assert settings.PIPELINE_MODE == "legacy"


def test_claude_coerces_render_dpi():
    """When AI_PROVIDER='claude', EXAMINER_RENDER_DPI uses Claude-specific value."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        CLAUDE_EXAMINER_RENDER_DPI=150,
    )
    assert settings.EXAMINER_RENDER_DPI == 150


def test_gemini_preserves_native_pdf_mode():
    """When AI_PROVIDER='gemini', PIPELINE_MODE='native_pdf' is preserved."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        PIPELINE_MODE="native_pdf",
    )
    assert settings.PIPELINE_MODE == "native_pdf"


def test_gemini_render_dpi_unchanged():
    """When AI_PROVIDER='gemini', EXAMINER_RENDER_DPI is not overridden."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        EXAMINER_RENDER_DPI=72,
    )
    assert settings.EXAMINER_RENDER_DPI == 72


def test_claude_specific_examiner_settings():
    """Claude-specific batch sizes and concurrency are configurable."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        CLAUDE_EXAMINER_BATCH_SIZE=8,
        CLAUDE_EXAMINER_BATCH_SIZE_TEXT=15,
        CLAUDE_EXAMINER_CONCURRENCY=5,
        CLAUDE_EXAMINER_STAGGER_MS=300,
    )
    assert settings.CLAUDE_EXAMINER_BATCH_SIZE == 8
    assert settings.CLAUDE_EXAMINER_BATCH_SIZE_TEXT == 15
    assert settings.CLAUDE_EXAMINER_CONCURRENCY == 5
    assert settings.CLAUDE_EXAMINER_STAGGER_MS == 300


# ---------------------------------------------------------------------------
# Model string resolution
# ---------------------------------------------------------------------------


def test_model_for_gemini_provider():
    """_get_model_for_provider('gemini') returns Gemini model."""
    from app.ai.base_service import _get_model_for_provider
    assert _get_model_for_provider("gemini") == "gemini/gemini-2.5-flash"


def test_model_for_claude_provider():
    """_get_model_for_provider('claude') returns Claude model."""
    from app.ai.base_service import _get_model_for_provider
    from app.ai.claude_provider import CLAUDE_MODEL
    assert _get_model_for_provider("claude") == CLAUDE_MODEL
    assert "anthropic" in CLAUDE_MODEL
    assert "claude" in CLAUDE_MODEL


# ---------------------------------------------------------------------------
# BaseAIService provider initialization
# ---------------------------------------------------------------------------


def test_base_service_gemini_init():
    """BaseAIService uses Gemini model when AI_PROVIDER='gemini'."""
    from app.ai.base_service import BaseAIService, _configured
    import app.ai.base_service as mod

    gemini_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
    )
    # Reset configured state
    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=gemini_settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert service._provider == "gemini"
        assert service.model == "gemini/gemini-2.5-flash"
    mod._configured = False


def test_base_service_claude_init():
    """BaseAIService uses Claude model when AI_PROVIDER='claude'."""
    from app.ai.base_service import BaseAIService
    from app.ai.claude_provider import CLAUDE_MODEL
    import app.ai.base_service as mod

    claude_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=claude_settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert service._provider == "claude"
        assert service.model == CLAUDE_MODEL
    mod._configured = False


# ---------------------------------------------------------------------------
# Claude configure sets ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------


def test_configure_claude_sets_env():
    """configure_claude sets ANTHROPIC_API_KEY in environment."""
    from app.ai.claude_provider import configure_claude

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test-key-123",
    )
    # Clean up after test
    old_val = os.environ.get("ANTHROPIC_API_KEY")
    try:
        configure_claude(settings)
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-test-key-123"
    finally:
        if old_val is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_val
        elif "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]


# ---------------------------------------------------------------------------
# Version tracker: dynamic platform/model
# ---------------------------------------------------------------------------


def test_version_info_gemini():
    """collect_version_info returns Gemini platform/model for gemini provider."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        PIPELINE_MODE="legacy",
    )
    info = collect_version_info(settings)
    assert info["ai_platform"] == "gemini"
    assert info["ai_model"] == "gemini/gemini-2.5-flash"
    assert info["ocr_engine"] == "gemini_vision"
    assert info["version_metadata"]["ai_platform"] == "gemini"


def test_version_info_gemini_native_pdf():
    """collect_version_info returns correct OCR engine for Gemini native_pdf mode."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        PIPELINE_MODE="native_pdf",
    )
    info = collect_version_info(settings)
    assert info["ocr_engine"] == "gemini_native_pdf"


def test_version_info_claude():
    """collect_version_info returns Anthropic platform/model for claude provider."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        PIPELINE_MODE="legacy",  # Claude coerces to legacy anyway
    )
    info = collect_version_info(settings)
    assert info["ai_platform"] == "anthropic"
    assert info["ai_model"] == CLAUDE_MODEL
    assert info["ocr_engine"] == "claude_vision"
    assert info["version_metadata"]["ai_platform"] == "anthropic"
    assert info["version_metadata"]["ai_model"] == CLAUDE_MODEL


# ---------------------------------------------------------------------------
# Examiner cache key isolation
# ---------------------------------------------------------------------------


def test_examiner_cache_keys_differ_between_providers():
    """Same input file hash produces different examiner cache keys for different providers."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_examiner_cache_key,
    )

    input_hash = "abc123deadbeef"

    gemini_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        PIPELINE_MODE="legacy",
    )
    gemini_info = collect_version_info(gemini_settings)
    gemini_key = compute_examiner_cache_key(input_hash, gemini_info)

    claude_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        PIPELINE_MODE="legacy",
    )
    claude_info = collect_version_info(claude_settings)
    claude_key = compute_examiner_cache_key(input_hash, claude_info)

    assert gemini_key != claude_key, "Cache keys must differ between providers"


# ---------------------------------------------------------------------------
# Examiner batch config
# ---------------------------------------------------------------------------


def test_examiner_batch_config_gemini():
    """TitleExaminerAgent._get_batch_config() returns Gemini settings."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        EXAMINER_BATCH_SIZE=10,
        EXAMINER_BATCH_SIZE_TEXT=25,
        GOOGLE_API_KEY="test-key",
    )
    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["batch_size_image"] == 10
        assert config["batch_size_text"] == 25
    mod._configured = False


def test_examiner_batch_config_claude():
    """TitleExaminerAgent._get_batch_config() returns Claude settings."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
        CLAUDE_EXAMINER_BATCH_SIZE=8,
        CLAUDE_EXAMINER_BATCH_SIZE_TEXT=15,
        CLAUDE_EXAMINER_CONCURRENCY=5,
        CLAUDE_EXAMINER_STAGGER_MS=300,
    )
    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["batch_size_image"] == 8
        assert config["batch_size_text"] == 15
        assert config["concurrency"] == 5
        assert config["stagger_ms"] == 300
    mod._configured = False


# ---------------------------------------------------------------------------
# Claude context cache returns None (implicit caching)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_create_context_cache_returns_none():
    """For Claude provider, create_context_cache() returns None."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        cache_name = await service.create_context_cache(
            system_prompt="test prompt",
            json_schema={"type": "object"},
        )
        assert cache_name is None
    mod._configured = False


# ---------------------------------------------------------------------------
# Claude structured output via tool_use (mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_call_json_structured_uses_tool_use():
    """Claude's call_json_structured dispatches to call_json_structured_claude."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )

    mock_result = {"sections": [], "flags": []}

    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.claude_provider.call_json_structured_claude", return_value=mock_result) as mock_claude:
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        result = await service.call_json_structured(
            system_prompt="test",
            messages=[{"role": "user", "content": "test"}],
            json_schema={"type": "object"},
        )
        assert result == mock_result
        mock_claude.assert_called_once()
        # Verify the model passed is Claude's model
        call_kwargs = mock_claude.call_args
        assert "anthropic" in call_kwargs.kwargs["model"]
    mod._configured = False


@pytest.mark.asyncio
async def test_gemini_call_json_structured_dispatches_correctly():
    """Gemini's call_json_structured dispatches to call_json_structured_gemini."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
    )

    mock_result = {"sections": [], "flags": []}

    mod._configured = False
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.call_json_structured_gemini", return_value=mock_result) as mock_gemini:
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        result = await service.call_json_structured(
            system_prompt="test",
            messages=[{"role": "user", "content": "test"}],
            json_schema={"type": "object"},
        )
        assert result == mock_result
        mock_gemini.assert_called_once()
    mod._configured = False
