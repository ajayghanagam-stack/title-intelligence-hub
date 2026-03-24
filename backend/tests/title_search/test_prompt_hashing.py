"""Tests for prompt and tool schema hashing infrastructure.

Verifies that:
1. Prompts and tools are importable module-level constants (not dynamic)
2. Hash computation is deterministic
3. Any change to prompt/tool content produces a different hash
4. version_tracker integrates all agent hashes correctly
"""
import json

from app.micro_apps.title_search.ai.document_parser_agent import (
    PARSER_SYSTEM_PROMPT, PARSER_TOOL,
)
from app.micro_apps.title_search.ai.chain_builder_agent import (
    CHAIN_SYSTEM_PROMPT, CHAIN_TOOL,
)
from app.micro_apps.title_search.ai.anomaly_detector_agent import (
    ANOMALY_SYSTEM_PROMPT, ANOMALY_TOOL,
)
from app.micro_apps.title_search.pipeline.version_tracker import (
    hash_string,
    collect_version_info,
    RULES_VERSION,
)
from app.config import Settings


def _test_settings():
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        JWT_SECRET="test-secret",
        DEBUG=True,
    )


# ---------------------------------------------------------------------------
# Prompt constants are non-empty strings
# ---------------------------------------------------------------------------

def test_parser_prompt_is_nonempty_string():
    assert isinstance(PARSER_SYSTEM_PROMPT, str)
    assert len(PARSER_SYSTEM_PROMPT) > 50


def test_chain_prompt_is_nonempty_string():
    assert isinstance(CHAIN_SYSTEM_PROMPT, str)
    assert len(CHAIN_SYSTEM_PROMPT) > 50


def test_anomaly_prompt_is_nonempty_string():
    assert isinstance(ANOMALY_SYSTEM_PROMPT, str)
    assert len(ANOMALY_SYSTEM_PROMPT) > 50


# ---------------------------------------------------------------------------
# Tool schemas are valid dicts with required fields
# ---------------------------------------------------------------------------

def test_parser_tool_has_required_fields():
    assert isinstance(PARSER_TOOL, dict)
    assert "name" in PARSER_TOOL
    assert "input_schema" in PARSER_TOOL
    assert PARSER_TOOL["input_schema"]["type"] == "object"
    assert "doc_type" in PARSER_TOOL["input_schema"]["properties"]


def test_chain_tool_has_required_fields():
    assert isinstance(CHAIN_TOOL, dict)
    assert "name" in CHAIN_TOOL
    assert "input_schema" in CHAIN_TOOL
    assert "chain_links" in CHAIN_TOOL["input_schema"]["properties"]


def test_anomaly_tool_has_required_fields():
    assert isinstance(ANOMALY_TOOL, dict)
    assert "name" in ANOMALY_TOOL
    assert "input_schema" in ANOMALY_TOOL
    assert "flags" in ANOMALY_TOOL["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------

def test_prompt_hash_deterministic():
    """Same prompt always produces the same hash."""
    h1 = hash_string(PARSER_SYSTEM_PROMPT)
    h2 = hash_string(PARSER_SYSTEM_PROMPT)
    assert h1 == h2
    assert len(h1) == 64


def test_tool_hash_deterministic():
    """Same tool schema always produces the same hash."""
    h1 = hash_string(json.dumps(PARSER_TOOL, sort_keys=True))
    h2 = hash_string(json.dumps(PARSER_TOOL, sort_keys=True))
    assert h1 == h2


def test_different_prompts_produce_different_hashes():
    """Parser and chain prompts produce different hashes."""
    h_parser = hash_string(PARSER_SYSTEM_PROMPT)
    h_chain = hash_string(CHAIN_SYSTEM_PROMPT)
    h_anomaly = hash_string(ANOMALY_SYSTEM_PROMPT)
    assert h_parser != h_chain
    assert h_chain != h_anomaly
    assert h_parser != h_anomaly


def test_different_tools_produce_different_hashes():
    """Parser and chain tools produce different hashes."""
    h_parser = hash_string(json.dumps(PARSER_TOOL, sort_keys=True))
    h_chain = hash_string(json.dumps(CHAIN_TOOL, sort_keys=True))
    h_anomaly = hash_string(json.dumps(ANOMALY_TOOL, sort_keys=True))
    assert h_parser != h_chain
    assert h_chain != h_anomaly


def test_prompt_change_changes_hash():
    """Modifying a prompt produces a different hash (simulated)."""
    original = hash_string(PARSER_SYSTEM_PROMPT)
    modified = hash_string(PARSER_SYSTEM_PROMPT + " additional instruction")
    assert original != modified


def test_tool_change_changes_hash():
    """Modifying a tool schema produces a different hash (simulated)."""
    original = hash_string(json.dumps(PARSER_TOOL, sort_keys=True))
    modified_tool = {**PARSER_TOOL, "description": "Modified description"}
    modified = hash_string(json.dumps(modified_tool, sort_keys=True))
    assert original != modified


# ---------------------------------------------------------------------------
# version_tracker integration
# ---------------------------------------------------------------------------

def test_version_info_includes_all_hashes():
    """collect_version_info includes hashes for all 3 agents."""
    import app.micro_apps.title_search.pipeline.version_tracker as vt
    vt._cached_version_info = None
    vt._cached_version_key = None

    info = collect_version_info(_test_settings())

    # Parser
    assert info["parser_prompt_hash"] == hash_string(PARSER_SYSTEM_PROMPT)
    assert info["parser_tool_hash"] == hash_string(json.dumps(PARSER_TOOL, sort_keys=True))

    # Chain
    assert info["chain_prompt_hash"] == hash_string(CHAIN_SYSTEM_PROMPT)
    assert info["chain_tool_hash"] == hash_string(json.dumps(CHAIN_TOOL, sort_keys=True))

    # Anomaly
    assert info["anomaly_prompt_hash"] == hash_string(ANOMALY_SYSTEM_PROMPT)
    assert info["anomaly_tool_hash"] == hash_string(json.dumps(ANOMALY_TOOL, sort_keys=True))


def test_version_info_includes_rules_version():
    """collect_version_info includes RULES_VERSION from flag_rules."""
    import app.micro_apps.title_search.pipeline.version_tracker as vt
    vt._cached_version_info = None
    vt._cached_version_key = None

    info = collect_version_info(_test_settings())
    assert info["rules_version"] == RULES_VERSION
    assert info["rules_version"] == "ta_flag_rules_v1"


def test_all_hashes_are_64_char_hex():
    """All hash values are valid SHA-256 hex strings."""
    import app.micro_apps.title_search.pipeline.version_tracker as vt
    vt._cached_version_info = None
    vt._cached_version_key = None

    info = collect_version_info(_test_settings())
    hash_keys = [
        "parser_prompt_hash", "chain_prompt_hash", "anomaly_prompt_hash",
        "parser_tool_hash", "chain_tool_hash", "anomaly_tool_hash",
    ]
    for key in hash_keys:
        assert len(info[key]) == 64, f"{key} hash is not 64 chars"
        assert all(c in "0123456789abcdef" for c in info[key]), f"{key} is not valid hex"
