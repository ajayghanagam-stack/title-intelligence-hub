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


def test_default_provider_is_claude():
    """Default AI_PROVIDER is 'claude' (when not overridden by env)."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
    )
    assert settings.AI_PROVIDER == "claude"


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
        CLAUDE_EXAMINER_RENDER_DPI=100,
    )
    assert settings.EXAMINER_RENDER_DPI == 100


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
        CLAUDE_EXAMINER_BATCH_SIZE_TEXT=25,
        CLAUDE_EXAMINER_CONCURRENCY=8,
        CLAUDE_EXAMINER_STAGGER_MS=100,
        CLAUDE_EXAMINER_RPM=50,
    )
    assert settings.CLAUDE_EXAMINER_BATCH_SIZE == 8
    assert settings.CLAUDE_EXAMINER_BATCH_SIZE_TEXT == 25
    assert settings.CLAUDE_EXAMINER_CONCURRENCY == 8
    assert settings.CLAUDE_EXAMINER_STAGGER_MS == 100
    assert settings.CLAUDE_EXAMINER_RPM == 50


# ---------------------------------------------------------------------------
# Model string resolution
# ---------------------------------------------------------------------------


def test_model_for_gemini_provider():
    """_get_model_for_provider('gemini') returns Gemini model (AI Studio)."""
    from app.ai.base_service import _get_model_for_provider
    ai_studio_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        VERTEX_AI=False,
    )
    with patch("app.ai.gemini_provider.get_settings", return_value=ai_studio_settings):
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
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    gemini_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        VERTEX_AI=False,
    )
    # Reset configured state
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=gemini_settings), \
         patch("app.ai.gemini_provider.get_settings", return_value=gemini_settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert service._provider == "gemini"
        assert service.model == "gemini/gemini-2.5-flash"
    mod._configured_providers = set()


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
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=claude_settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert service._provider == "claude"
        assert service.model == CLAUDE_MODEL
    mod._configured_providers = set()


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
    """collect_version_info returns Gemini platform/model for gemini provider (AI Studio)."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        PIPELINE_MODE="legacy",
        VERTEX_AI=False,
    )
    with patch("app.ai.gemini_provider.get_settings", return_value=settings):
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
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["batch_size_image"] == 10
        assert config["batch_size_text"] == 25
    mod._configured_providers = set()


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
        CLAUDE_EXAMINER_BATCH_SIZE_TEXT=25,
        CLAUDE_EXAMINER_CONCURRENCY=8,
        CLAUDE_EXAMINER_STAGGER_MS=100,
        CLAUDE_EXAMINER_RPM=50,
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["batch_size_image"] == 8
        assert config["batch_size_text"] == 25
        assert config["concurrency"] == 8
        assert config["stagger_ms"] == 100
        assert config["rpm"] == 50
    mod._configured_providers = set()


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
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        cache_name = await service.create_context_cache(
            system_prompt="test prompt",
            json_schema={"type": "object"},
        )
        assert cache_name is None
    mod._configured_providers = set()


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

    mod._configured_providers = set()
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
    mod._configured_providers = set()


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

    mod._configured_providers = set()
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
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Performance optimization config defaults
# ---------------------------------------------------------------------------


def test_claude_optimized_defaults():
    """Verify Claude performance optimization defaults are applied."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
    )
    # Optimized defaults
    assert settings.CLAUDE_EXAMINER_RENDER_DPI == 100  # was 150
    assert settings.CLAUDE_EXAMINER_BATCH_SIZE_TEXT == 25  # was 15
    assert settings.CLAUDE_EXAMINER_CONCURRENCY == 8  # was 5
    assert settings.CLAUDE_EXAMINER_STAGGER_MS == 100  # was 300
    assert settings.CLAUDE_EXAMINER_RPM == 50
    assert settings.TRIAGE_SKIP_BELOW == 200  # was 80


def test_triage_skip_below_raised():
    """TRIAGE_SKIP_BELOW defaults to 200 (was 80)."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
    )
    assert settings.TRIAGE_SKIP_BELOW == 200


# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_controller_token_bucket():
    """RateLimitController with RPM limits requests proactively."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

    # 60 RPM = 1 request per second
    controller = RateLimitController(max_concurrency=5, stagger_ms=0, requests_per_minute=60)
    # First acquire should be fast (token available)
    import time
    t0 = time.monotonic()
    await controller.acquire(0)
    controller.release()
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0  # should be instant


@pytest.mark.asyncio
async def test_rate_limit_controller_no_rpm():
    """RateLimitController with rpm=0 doesn't throttle."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

    controller = RateLimitController(max_concurrency=5, stagger_ms=0, requests_per_minute=0)
    import time
    t0 = time.monotonic()
    await controller.acquire(0)
    controller.release()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5


def test_rate_limit_controller_metrics_include_token_waits():
    """Token wait count is tracked in metrics."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

    controller = RateLimitController(max_concurrency=5, stagger_ms=0, requests_per_minute=60)
    metrics = controller.get_metrics()
    assert "token_waits" in metrics
    assert metrics["token_waits"] == 0


# ---------------------------------------------------------------------------
# In-memory page image cache
# ---------------------------------------------------------------------------


def test_page_image_cache_module_level():
    """Verify _page_image_cache dict exists at module level."""
    from app.micro_apps.title_intelligence.pipeline.stages import _page_image_cache
    assert isinstance(_page_image_cache, dict)


# ---------------------------------------------------------------------------
# Text skip render threshold
# ---------------------------------------------------------------------------


def test_text_skip_render_threshold_constant():
    """TEXT_SKIP_RENDER_THRESHOLD is set to 200."""
    from app.micro_apps.title_intelligence.pipeline.stages import TEXT_SKIP_RENDER_THRESHOLD
    assert TEXT_SKIP_RENDER_THRESHOLD == 200


def test_batch_config_includes_rpm():
    """Claude batch config includes 'rpm' key."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert "rpm" in config
        assert config["rpm"] == 50
    mod._configured_providers = set()


def test_gemini_batch_config_rpm_zero():
    """Gemini batch config has rpm=0 (no proactive RPM limit)."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["rpm"] == 0
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Hybrid provider config
# ---------------------------------------------------------------------------


def test_hybrid_provider_config():
    """AI_PROVIDER='hybrid' is accepted when both keys are present."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-gemini-key",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert settings.AI_PROVIDER == "hybrid"


def test_hybrid_forces_native_pdf_mode():
    """Hybrid mode forces PIPELINE_MODE to native_pdf."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-gemini-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        PIPELINE_MODE="legacy",
    )
    assert settings.PIPELINE_MODE == "native_pdf"


def test_hybrid_requires_google_api_key():
    """Hybrid mode raises ValueError if GOOGLE_API_KEY is missing (non-Vertex)."""
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="hybrid",
            GOOGLE_API_KEY="",
            ANTHROPIC_API_KEY="sk-ant-test",
            VERTEX_AI=False,
        )


def test_hybrid_requires_anthropic_api_key():
    """Hybrid mode raises ValueError if ANTHROPIC_API_KEY is missing."""
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="hybrid",
            GOOGLE_API_KEY="test-gemini-key",
            ANTHROPIC_API_KEY="",
        )


def test_hybrid_does_not_coerce_render_dpi():
    """Hybrid mode does NOT override EXAMINER_RENDER_DPI (no image rendering needed)."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-gemini-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        EXAMINER_RENDER_DPI=72,
    )
    assert settings.EXAMINER_RENDER_DPI == 72


# ---------------------------------------------------------------------------
# Hybrid model resolution
# ---------------------------------------------------------------------------


def test_model_for_hybrid_provider():
    """_get_model_for_provider('hybrid') returns Gemini model (vision pass, AI Studio)."""
    from app.ai.base_service import _get_model_for_provider
    ai_studio_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        VERTEX_AI=False,
    )
    with patch("app.ai.gemini_provider.get_settings", return_value=ai_studio_settings):
        assert _get_model_for_provider("hybrid") == "gemini/gemini-2.5-flash"


def test_get_claude_model_helper():
    """_get_claude_model() returns Claude model string."""
    from app.ai.base_service import _get_claude_model
    from app.ai.claude_provider import CLAUDE_MODEL
    assert _get_claude_model() == CLAUDE_MODEL


# ---------------------------------------------------------------------------
# Hybrid BaseAIService init
# ---------------------------------------------------------------------------


def test_base_service_hybrid_init():
    """BaseAIService uses Gemini model when AI_PROVIDER='hybrid' (AI Studio)."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        VERTEX_AI=False,
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.get_settings", return_value=settings):
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert service._provider == "hybrid"
        assert service.model == "gemini/gemini-2.5-flash"
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Hybrid ensures both providers configured
# ---------------------------------------------------------------------------


def test_hybrid_configures_both_providers():
    """Hybrid mode calls both configure_gemini and configure_claude."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.configure_gemini") as mock_gemini, \
         patch("app.ai.claude_provider.configure_claude") as mock_claude:
        BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        mock_gemini.assert_called_once_with(settings)
        mock_claude.assert_called_once_with(settings)
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Content policy error detection
# ---------------------------------------------------------------------------


def test_is_content_policy_error_detects_violations():
    """_is_content_policy_error detects various content policy error strings."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import _is_content_policy_error

    assert _is_content_policy_error(
        Exception("litellm.ContentPolicyViolationError: blocked")
    )
    assert _is_content_policy_error(
        Exception("Output blocked by content filtering policy")
    )
    assert _is_content_policy_error(
        Exception("content_policy violation detected")
    )


def test_is_content_policy_error_rejects_non_policy():
    """_is_content_policy_error returns False for unrelated errors."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import _is_content_policy_error

    assert not _is_content_policy_error(Exception("429 rate limit"))
    assert not _is_content_policy_error(Exception("timeout"))
    assert not _is_content_policy_error(Exception("connection refused"))


# ---------------------------------------------------------------------------
# Hybrid version tracking
# ---------------------------------------------------------------------------


def test_version_info_hybrid():
    """collect_version_info returns hybrid platform/model for hybrid provider."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        PIPELINE_MODE="native_pdf",
    )
    info = collect_version_info(settings)
    assert info["ai_platform"] == "hybrid"
    assert "gemini" in info["ai_model"]
    assert "anthropic" in info["ai_model"] or "claude" in info["ai_model"]
    assert info["ocr_engine"] == "gemini_native_pdf"
    assert info["version_metadata"]["ai_platform"] == "hybrid"


def test_hybrid_cache_key_differs_from_gemini_and_claude():
    """Hybrid cache key is distinct from both Gemini-only and Claude-only keys."""
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_examiner_cache_key,
    )

    input_hash = "abc123deadbeef"

    gemini_info = collect_version_info(Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret", DEBUG=True,
        AI_PROVIDER="gemini", PIPELINE_MODE="legacy",
    ))
    claude_info = collect_version_info(Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret", DEBUG=True,
        AI_PROVIDER="claude", PIPELINE_MODE="legacy",
    ))
    hybrid_info = collect_version_info(Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret", DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test", ANTHROPIC_API_KEY="test",
    ))

    gemini_key = compute_examiner_cache_key(input_hash, gemini_info)
    claude_key = compute_examiner_cache_key(input_hash, claude_info)
    hybrid_key = compute_examiner_cache_key(input_hash, hybrid_info)

    assert hybrid_key != gemini_key, "Hybrid cache key must differ from Gemini"
    assert hybrid_key != claude_key, "Hybrid cache key must differ from Claude"


# ---------------------------------------------------------------------------
# Hybrid batch config
# ---------------------------------------------------------------------------


def test_hybrid_batch_config_uses_gemini_settings():
    """Hybrid mode uses Gemini batch sizes (Gemini handles vision pass)."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        EXAMINER_BATCH_SIZE=10,
        EXAMINER_BATCH_SIZE_TEXT=25,
        NATIVE_PDF_CONCURRENCY=12,
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        config = agent._get_batch_config()
        assert config["batch_size_image"] == 10
        assert config["batch_size_text"] == 25
        assert config["concurrency"] == 12
        assert config["rpm"] == 0
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Hybrid examine_pdf_batch (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_examine_pdf_batch_two_pass():
    """Hybrid examine_pdf_batch calls Gemini for transcription then Claude for extraction."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
    )

    # Mock Gemini transcription result
    gemini_result = {
        "page_transcriptions": [
            {"page_number": 1, "text": "COMMITMENT FOR TITLE INSURANCE"},
            {"page_number": 2, "text": "Schedule A - Property Details"},
        ]
    }
    gemini_usage = {"input_tokens": 1000, "output_tokens": 500}

    # Mock Claude extraction result
    claude_result = {
        "sections": [{"section_type": "schedule_a", "start_page": 1, "end_page": 2}],
        "parties": [{"label": "Owner", "value": {"name": "John Doe", "role": "current_owner", "entity_type": "individual", "marital_status": "married", "deceased": False, "date_of_death": ""}}],
        "properties": [],
        "requirements": [],
        "exceptions": [],
        "endorsements": [],
        "policy_info_items": [],
        "compliance_items": [],
        "chain_of_title_items": [],
        "flags": [{"flag_type": "name_discrepancy", "severity": "medium", "title": "Name issue", "description": "desc", "ai_explanation": "expl", "evidence_refs": []}],
    }
    claude_usage = {"input_tokens": 2000, "output_tokens": 1000}

    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=settings):
        agent = TitleExaminerAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        # Disable context cache for test
        agent._cache_name = "SKIP"

        with patch.object(agent, "call_json_structured", return_value=(gemini_result, gemini_usage)) as mock_gemini, \
             patch.object(agent, "call_json_structured_claude", return_value=(claude_result, claude_usage)) as mock_claude:
            # Need to make _ensure_context_cache return None
            agent._cache_name = None
            with patch.object(agent, "_ensure_context_cache", return_value=None):
                result = await agent.examine_pdf_batch(
                    pdf_bytes=b"fake-pdf",
                    page_range=(1, 2),
                    total_pages=2,
                    batch_index=0,
                    total_batches=1,
                )

            # Verify Gemini was called for transcription
            mock_gemini.assert_called_once()
            # Verify Claude was called for extraction
            mock_claude.assert_called_once()

            # Verify merged result
            assert len(result.page_transcriptions) == 2
            assert len(result.sections) == 1
            assert len(result.extractions) == 1
            assert len(result.flags) == 1

            # Verify token aggregation
            assert result.input_tokens == 3000  # 1000 + 2000
            assert result.output_tokens == 1500  # 500 + 1000
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Hybrid context cache uses Gemini
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_create_context_cache_uses_gemini():
    """For hybrid provider, create_context_cache() uses Gemini (not None)."""
    from app.ai.base_service import BaseAIService
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="hybrid",
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.create_context_cache_gemini", return_value="cache-123") as mock_cache:
        service = BaseAIService(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        cache_name = await service.create_context_cache(
            system_prompt="test prompt",
            json_schema={"type": "object"},
        )
        assert cache_name == "cache-123"
        mock_cache.assert_called_once()
    mod._configured_providers = set()


# ---------------------------------------------------------------------------
# Transcription schema and prompt exist
# ---------------------------------------------------------------------------


def test_transcription_only_schema_defined():
    """TRANSCRIPTION_ONLY_JSON_SCHEMA only requires page_transcriptions."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TRANSCRIPTION_ONLY_JSON_SCHEMA

    assert TRANSCRIPTION_ONLY_JSON_SCHEMA["type"] == "object"
    assert "page_transcriptions" in TRANSCRIPTION_ONLY_JSON_SCHEMA["properties"]
    assert TRANSCRIPTION_ONLY_JSON_SCHEMA["required"] == ["page_transcriptions"]
    # Should NOT have sections, flags, etc.
    assert "sections" not in TRANSCRIPTION_ONLY_JSON_SCHEMA["properties"]
    assert "flags" not in TRANSCRIPTION_ONLY_JSON_SCHEMA["properties"]


def test_transcription_system_prompt_defined():
    """TRANSCRIPTION_SYSTEM_PROMPT exists and mentions transcription."""
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TRANSCRIPTION_SYSTEM_PROMPT

    assert "Transcribe" in TRANSCRIPTION_SYSTEM_PROMPT
    assert "faithfully" in TRANSCRIPTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Split provider: TI_CHAT_PROVIDER config
# ---------------------------------------------------------------------------


def test_ti_chat_provider_defaults_empty():
    """TI_CHAT_PROVIDER defaults to empty string (use AI_PROVIDER)."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        TI_CHAT_PROVIDER="",
    )
    assert settings.TI_CHAT_PROVIDER == ""


def test_ti_chat_provider_claude_requires_key():
    """TI_CHAT_PROVIDER='claude' raises if ANTHROPIC_API_KEY is missing."""
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="gemini",
            GOOGLE_API_KEY="test-key",
            TI_CHAT_PROVIDER="claude",
            ANTHROPIC_API_KEY="",
        )


def test_ti_chat_provider_gemini_requires_key():
    """TI_CHAT_PROVIDER='gemini' raises if GOOGLE_API_KEY is missing (non-Vertex)."""
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="claude",
            ANTHROPIC_API_KEY="sk-ant-test",
            TI_CHAT_PROVIDER="gemini",
            GOOGLE_API_KEY="",
            VERTEX_AI=False,
        )


def test_ti_chat_provider_claude_accepted():
    """TI_CHAT_PROVIDER='claude' is accepted when key is present."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        TI_CHAT_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert settings.TI_CHAT_PROVIDER == "claude"
    assert settings.AI_PROVIDER == "gemini"


# ---------------------------------------------------------------------------
# Split provider: ChatAgent override
# ---------------------------------------------------------------------------


def test_chat_agent_uses_override_provider():
    """ChatAgent uses TI_CHAT_PROVIDER when set, not AI_PROVIDER."""
    from app.micro_apps.title_intelligence.ai.chat_agent import ChatAgent
    from app.ai.claude_provider import CLAUDE_MODEL
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        TI_CHAT_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.chat_agent.get_settings", return_value=settings):
        agent = ChatAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert agent._provider == "claude"
        assert agent.model == CLAUDE_MODEL
    mod._configured_providers = set()


def test_chat_agent_falls_back_to_ai_provider():
    """ChatAgent uses AI_PROVIDER when TI_CHAT_PROVIDER is empty (AI Studio)."""
    from app.micro_apps.title_intelligence.ai.chat_agent import ChatAgent
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        TI_CHAT_PROVIDER="",
        VERTEX_AI=False,
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.chat_agent.get_settings", return_value=settings):
        agent = ChatAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        assert agent._provider == "gemini"
        assert agent.model == "gemini/gemini-2.5-flash"
    mod._configured_providers = set()


def test_split_provider_configures_both():
    """When AI_PROVIDER=gemini and TI_CHAT_PROVIDER=claude, both providers are configured."""
    import app.ai.base_service as mod

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        TI_CHAT_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    mod._configured_providers = set()
    with patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.micro_apps.title_intelligence.ai.chat_agent.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.configure_gemini") as mock_gemini, \
         patch("app.ai.claude_provider.configure_claude") as mock_claude:
        from app.micro_apps.title_intelligence.ai.chat_agent import ChatAgent
        agent = ChatAgent(org_id=uuid.UUID("00000000-0000-0000-0000-000000000010"))
        mock_gemini.assert_called_once()
        mock_claude.assert_called_once()
        assert agent._provider == "claude"
    mod._configured_providers = set()
