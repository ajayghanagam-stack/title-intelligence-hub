"""Tests for TA_AI_PROVIDER per-micro-app AI provider config.

Verifies config validation, per-agent provider override, and fallback behavior.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.config import Settings


TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


# ---------------------------------------------------------------------------
# Config: TA_AI_PROVIDER defaults and validation
# ---------------------------------------------------------------------------


def test_ta_ai_provider_defaults_claude():
    """TA_AI_PROVIDER defaults to 'claude' (TSA always uses Anthropic)."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert settings.TA_AI_PROVIDER == "claude"


def test_ta_ai_provider_empty_overrides_to_fallback():
    """TA_AI_PROVIDER='' falls back to AI_PROVIDER."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        TA_AI_PROVIDER="",
    )
    assert settings.TA_AI_PROVIDER == ""


def test_ta_ai_provider_claude_requires_key():
    """TA_AI_PROVIDER='claude' raises if ANTHROPIC_API_KEY is missing."""
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="gemini",
            GOOGLE_API_KEY="test-key",
            TA_AI_PROVIDER="claude",
            ANTHROPIC_API_KEY="",
        )


def test_ta_ai_provider_gemini_requires_key():
    """TA_AI_PROVIDER='gemini' raises if GOOGLE_API_KEY is missing."""
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            DEBUG=True,
            AI_PROVIDER="claude",
            ANTHROPIC_API_KEY="sk-ant-test",
            TA_AI_PROVIDER="gemini",
            GOOGLE_API_KEY="",
            VERTEX_AI=False,
        )


def test_ta_ai_provider_claude_accepted():
    """TA_AI_PROVIDER='claude' is accepted when key is present."""
    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER="gemini",
        GOOGLE_API_KEY="test-key",
        TA_AI_PROVIDER="claude",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert settings.TA_AI_PROVIDER == "claude"
    assert settings.AI_PROVIDER == "gemini"


# ---------------------------------------------------------------------------
# Agent override: each TA agent respects TA_AI_PROVIDER
# ---------------------------------------------------------------------------


def _make_settings(ta_provider: str = "claude", ai_provider: str = "gemini") -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
        AI_PROVIDER=ai_provider,
        GOOGLE_API_KEY="test-key",
        ANTHROPIC_API_KEY="sk-ant-test",
        TA_AI_PROVIDER=ta_provider,
        VERTEX_AI=False,
    )


def _create_agent(agent_cls, settings):
    """Instantiate a TA agent with patched settings."""
    import app.ai.base_service as mod

    mod._configured_providers = set()
    with patch("app.config.get_settings", return_value=settings), \
         patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.get_settings", return_value=settings):
        agent = agent_cls(org_id=TEST_ORG_ID)
    mod._configured_providers = set()
    return agent


def test_document_parser_agent_uses_ta_provider():
    """DocumentParserAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.document_parser_agent import DocumentParserAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(DocumentParserAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_chain_analysis_agent_uses_ta_provider():
    """ChainAnalysisAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.chain_analysis_agent import ChainAnalysisAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(ChainAnalysisAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_property_data_extractor_uses_ta_provider():
    """PropertyDataExtractorAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.property_data_extractor import PropertyDataExtractorAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(PropertyDataExtractorAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_portal_discovery_agent_uses_ta_provider():
    """PortalDiscoveryAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.portal_discovery_agent import PortalDiscoveryAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(PortalDiscoveryAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_title_research_agent_uses_ta_provider():
    """TitleResearchAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.title_research_agent import TitleResearchAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(TitleResearchAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_package_agent_uses_ta_provider():
    """PackageAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.package_agent import PackageAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(PackageAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_chain_builder_agent_uses_ta_provider():
    """ChainBuilderAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.chain_builder_agent import ChainBuilderAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(ChainBuilderAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


def test_anomaly_detector_agent_uses_ta_provider():
    """AnomalyDetectorAgent uses TA_AI_PROVIDER when set."""
    from app.micro_apps.title_search.ai.anomaly_detector_agent import AnomalyDetectorAgent
    from app.ai.claude_provider import CLAUDE_MODEL

    settings = _make_settings(ta_provider="claude")
    agent = _create_agent(AnomalyDetectorAgent, settings)
    assert agent._provider == "claude"
    assert agent.model == CLAUDE_MODEL


# ---------------------------------------------------------------------------
# Fallback: empty TA_AI_PROVIDER falls back to AI_PROVIDER
# ---------------------------------------------------------------------------


def test_document_parser_falls_back_to_ai_provider():
    """DocumentParserAgent uses AI_PROVIDER when TA_AI_PROVIDER is empty."""
    from app.micro_apps.title_search.ai.document_parser_agent import DocumentParserAgent

    settings = _make_settings(ta_provider="", ai_provider="gemini")
    agent = _create_agent(DocumentParserAgent, settings)
    assert agent._provider == "gemini"
    assert agent.model == "gemini/gemini-2.5-flash"


def test_chain_analysis_falls_back_to_ai_provider():
    """ChainAnalysisAgent uses AI_PROVIDER when TA_AI_PROVIDER is empty."""
    from app.micro_apps.title_search.ai.chain_analysis_agent import ChainAnalysisAgent

    settings = _make_settings(ta_provider="", ai_provider="gemini")
    agent = _create_agent(ChainAnalysisAgent, settings)
    assert agent._provider == "gemini"
    assert agent.model == "gemini/gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Split provider: AI_PROVIDER=gemini + TA_AI_PROVIDER=claude
# ---------------------------------------------------------------------------


def test_split_provider_configures_both():
    """When AI_PROVIDER=gemini and TA_AI_PROVIDER=claude, both providers are configured."""
    import app.ai.base_service as mod

    settings = _make_settings(ta_provider="claude", ai_provider="gemini")
    mod._configured_providers = set()
    with patch("app.config.get_settings", return_value=settings), \
         patch("app.ai.base_service.get_settings", return_value=settings), \
         patch("app.ai.gemini_provider.configure_gemini") as mock_gemini, \
         patch("app.ai.claude_provider.configure_claude") as mock_claude:
        from app.micro_apps.title_search.ai.document_parser_agent import DocumentParserAgent
        agent = DocumentParserAgent(org_id=TEST_ORG_ID)
        mock_gemini.assert_called_once()
        mock_claude.assert_called_once()
        assert agent._provider == "claude"
    mod._configured_providers = set()
