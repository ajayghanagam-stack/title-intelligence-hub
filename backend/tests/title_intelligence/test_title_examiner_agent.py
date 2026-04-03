"""Unit tests for TitleExaminerAgent (mock LLM)."""

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.micro_apps.title_intelligence.ai.title_examiner_agent import (
    TitleExaminerAgent,
    SYSTEM_PROMPT,
    SUBMIT_EXAMINATION_RESULTS_TOOL,
    EXAMINATION_JSON_SCHEMA,
    EXAMINATION_JSON_SCHEMA_TEXT_ONLY,
    TYPED_EXTRACTION_KEYS,
)
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerBatchResult,
    ExaminerConsolidatedResult,
    ExaminerExtraction,
    ExaminerFlag,
    ExaminerSection,
    PageTranscription,
)

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


MOCK_BATCH_RESULT = {
    "page_transcriptions": [
        {"page_number": 1, "text": "COMMITMENT FOR TITLE INSURANCE\nIssued by: First American Title"},
        {"page_number": 2, "text": "Schedule A\n1. Effective Date: January 15, 2024"},
    ],
    "sections": [
        {"section_type": "schedule_a", "start_page": 2, "end_page": 2, "confidence": 0.95},
    ],
    "extractions": [
        {
            "extraction_type": "policy_info",
            "label": "Effective Date",
            "value": {"date": "2024-01-15"},
            "evidence_refs": [{"page_number": 2, "text_snippet": "Effective Date: January 15, 2024"}],
            "confidence": 0.9,
        },
    ],
    "flags": [],
}


MOCK_BATCH_RESULT_WITH_FLAGS = {
    "page_transcriptions": [
        {"page_number": 3, "text": "Schedule B-I Requirements\n1. Pay off existing mortgage"},
    ],
    "sections": [
        {"section_type": "schedule_b1", "start_page": 3, "end_page": 3, "confidence": 0.9},
    ],
    "extractions": [
        {
            "extraction_type": "requirement",
            "label": "Requirement #1",
            "value": {"description": "Pay off existing mortgage", "requirement_number": 1},
            "evidence_refs": [{"page_number": 3, "text_snippet": "Pay off existing mortgage"}],
            "confidence": 0.85,
        },
    ],
    "flags": [
        {
            "flag_type": "unresolved_lien",
            "severity": "high",
            "title": "Outstanding Mortgage",
            "description": "Existing mortgage must be satisfied",
            "ai_explanation": "Schedule B-I lists a requirement to pay off an existing mortgage, indicating an unresolved lien.",
            "evidence_refs": [{"page_number": 3, "text_snippet": "Pay off existing mortgage"}],
        },
    ],
}

# Text-only batch result (no page_transcriptions)
MOCK_BATCH_RESULT_TEXT_ONLY = {
    "sections": [
        {"section_type": "schedule_a", "start_page": 1, "end_page": 2, "confidence": 0.95},
    ],
    "extractions": [
        {
            "extraction_type": "policy_info",
            "label": "Effective Date",
            "value": {"date": "2024-01-15"},
            "evidence_refs": [{"page_number": 1, "text_snippet": "Effective Date: January 15, 2024"}],
            "confidence": 0.9,
        },
    ],
    "flags": [],
}


@pytest.fixture
def agent():
    with patch("app.ai.base_service._ensure_configured"):
        return TitleExaminerAgent(TEST_ORG_ID)


class TestParseAndConsolidate:
    """Test parsing and consolidation without LLM calls."""

    def test_parse_batch_result(self, agent):
        result = agent._parse_batch_result(MOCK_BATCH_RESULT)
        assert isinstance(result, ExaminerBatchResult)
        assert len(result.page_transcriptions) == 2
        assert result.page_transcriptions[0].page_number == 1
        assert "COMMITMENT" in result.page_transcriptions[0].text
        assert len(result.sections) == 1
        assert result.sections[0].section_type == "schedule_a"
        assert len(result.extractions) == 1
        assert result.extractions[0].extraction_type == "policy_info"
        assert len(result.flags) == 0

    def test_parse_batch_result_with_flags(self, agent):
        result = agent._parse_batch_result(MOCK_BATCH_RESULT_WITH_FLAGS)
        assert len(result.flags) == 1
        assert result.flags[0].flag_type == "unresolved_lien"
        assert result.flags[0].severity == "high"

    def test_parse_empty_result(self, agent):
        result = agent._parse_batch_result({})
        assert len(result.page_transcriptions) == 0
        assert len(result.sections) == 0
        assert len(result.extractions) == 0
        assert len(result.flags) == 0

    def test_parse_text_only_result(self, agent):
        """Text-only batches have no page_transcriptions key."""
        result = agent._parse_batch_result(MOCK_BATCH_RESULT_TEXT_ONLY)
        assert len(result.page_transcriptions) == 0
        assert len(result.sections) == 1
        assert len(result.extractions) == 1

    def test_consolidate_single_batch(self, agent):
        batch = agent._parse_batch_result(MOCK_BATCH_RESULT)
        consolidated = agent.consolidate([batch])
        assert isinstance(consolidated, ExaminerConsolidatedResult)
        assert len(consolidated.page_transcriptions) == 2
        assert len(consolidated.sections) == 1
        assert len(consolidated.extractions) == 1

    def test_consolidate_multiple_batches(self, agent):
        batch1 = agent._parse_batch_result(MOCK_BATCH_RESULT)
        batch2 = agent._parse_batch_result(MOCK_BATCH_RESULT_WITH_FLAGS)
        consolidated = agent.consolidate([batch1, batch2])

        assert len(consolidated.page_transcriptions) == 3  # pages 1, 2, 3
        assert len(consolidated.sections) == 2  # schedule_a + schedule_b1
        assert len(consolidated.extractions) == 2  # policy_info + requirement
        assert len(consolidated.flags) == 1  # unresolved_lien

    def test_consolidate_overlap_pages(self, agent):
        """Later batch's transcription wins for overlapping pages."""
        batch1 = ExaminerBatchResult(
            page_transcriptions=[
                PageTranscription(page_number=1, text="old text page 1"),
                PageTranscription(page_number=2, text="old text page 2"),
            ],
        )
        batch2 = ExaminerBatchResult(
            page_transcriptions=[
                PageTranscription(page_number=2, text="new text page 2"),
                PageTranscription(page_number=3, text="text page 3"),
            ],
        )
        consolidated = agent.consolidate([batch1, batch2])
        page_map = {t.page_number: t.text for t in consolidated.page_transcriptions}
        assert page_map[2] == "new text page 2"  # later batch wins
        assert len(consolidated.page_transcriptions) == 3

    def test_consolidate_merge_adjacent_sections(self, agent):
        """Adjacent sections of same type merge."""
        batch1 = ExaminerBatchResult(
            sections=[ExaminerSection(section_type="schedule_a", start_page=1, end_page=2, confidence=0.9)],
        )
        batch2 = ExaminerBatchResult(
            sections=[ExaminerSection(section_type="schedule_a", start_page=3, end_page=4, confidence=0.95)],
        )
        consolidated = agent.consolidate([batch1, batch2])
        assert len(consolidated.sections) == 1
        assert consolidated.sections[0].start_page == 1
        assert consolidated.sections[0].end_page == 4
        assert consolidated.sections[0].confidence == 0.95

    def test_consolidate_dedup_extractions(self, agent):
        """Extractions with same (type, label) keep higher confidence."""
        batch1 = ExaminerBatchResult(
            extractions=[
                ExaminerExtraction(
                    extraction_type="party", label="Buyer",
                    value={"name": "John"}, confidence=0.8,
                ),
            ],
        )
        batch2 = ExaminerBatchResult(
            extractions=[
                ExaminerExtraction(
                    extraction_type="party", label="Buyer",
                    value={"name": "John Doe"}, confidence=0.95,
                ),
            ],
        )
        consolidated = agent.consolidate([batch1, batch2])
        assert len(consolidated.extractions) == 1
        assert consolidated.extractions[0].confidence == 0.95
        assert consolidated.extractions[0].value["name"] == "John Doe"


class TestStaticBatchContext:
    """Test static batch context building."""

    def test_build_static_batch_context_single_batch(self, agent):
        """Single-batch documents need no context."""
        context = agent._build_static_batch_context(0, 1, 10)
        assert context is None

    def test_build_static_batch_context_multi_batch(self, agent):
        """Multi-batch documents get position info."""
        context = agent._build_static_batch_context(0, 3, 50)
        assert context is not None
        assert "1 of 3" in context["batch_position"]
        assert context["total_pages"] == 50

    def test_build_static_batch_context_last_batch(self, agent):
        context = agent._build_static_batch_context(2, 3, 50)
        assert "3 of 3" in context["batch_position"]

    def test_format_static_context(self, agent):
        context = {
            "batch_position": "Batch 1 of 3",
            "total_pages": 50,
        }
        text = agent._format_static_context(context)
        assert "DOCUMENT CONTEXT" in text
        assert "Batch 1 of 3" in text
        assert "50 total pages" in text
        assert "parallel" in text


class TestSmartBatching:
    """Test smart batch sizing logic."""

    def test_build_smart_batches_empty(self, agent):
        batches = TitleExaminerAgent._build_smart_batches([], 10, 25, 1)
        assert batches == []

    def test_build_smart_batches_all_text(self, agent):
        """All text pages should use larger batch size."""
        pages = [(i, None, f"text for page {i}") for i in range(1, 26)]
        batches = TitleExaminerAgent._build_smart_batches(pages, 10, 25, 1)
        assert len(batches) == 1
        assert len(batches[0]) == 25

    def test_build_smart_batches_all_image(self, agent):
        """All image pages should use smaller batch size."""
        pages = [(i, b"img", None) for i in range(1, 21)]
        # With overlap=1, 20 pages at batch_size=10 → 3 batches (10, 10, 2)
        batches = TitleExaminerAgent._build_smart_batches(pages, 10, 25, 1)
        assert len(batches) == 3
        assert len(batches[0]) == 10

    def test_build_smart_batches_mixed(self, agent):
        """Mixed pages: text group gets 25-size, image group gets 10-size."""
        pages = (
            [(i, None, f"text page {i}") for i in range(1, 11)]  # 10 text
            + [(i, b"img", None) for i in range(11, 16)]         # 5 image
        )
        batches = TitleExaminerAgent._build_smart_batches(pages, 10, 25, 0)
        assert len(batches) == 2  # 1 text batch + 1 image batch
        assert len(batches[0]) == 10  # text batch
        assert len(batches[1]) == 5   # image batch

    def test_build_smart_batches_typical_50_page_pdf(self, agent):
        """Typical 50-page PDF: 45 text + 5 image → 2 text batches + 1 image batch."""
        pages = (
            [(i, None, f"text page {i}") for i in range(1, 46)]  # 45 text
            + [(i, b"img", None) for i in range(46, 51)]          # 5 image
        )
        batches = TitleExaminerAgent._build_smart_batches(pages, 10, 25, 1)
        # 45 text pages with batch_size=25 and overlap=1 → batch[0]=25, batch[1]=21
        # 5 image pages with batch_size=10 → batch[2]=5
        assert len(batches) == 3


class TestHybridContent:
    """Test hybrid text+vision content building in examine_batch."""

    @pytest.mark.asyncio
    async def test_examine_batch_text_page(self, agent):
        """A page with text (no image) should produce text content blocks, not image_url."""
        page_images = [(1, None, "This is the full text of page one with enough content.")]

        # Mock both caching (returns None = not available) and the LLM call
        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (MOCK_BATCH_RESULT_TEXT_ONLY, {"input_tokens": 100, "output_tokens": 50})
                await agent.examine_batch(page_images)

                # Inspect the messages passed to call_json_structured
                call_args = mock_call.call_args
                messages = call_args.kwargs.get("messages") or call_args[1] if len(call_args[1]) > 1 else call_args.kwargs["messages"]
                content = messages[0]["content"]

                # Should have text blocks but no image_url blocks
                has_image = any(
                    block.get("type") == "image_url" for block in content
                )
                has_page_text = any(
                    block.get("type") == "text" and "This is the full text" in block.get("text", "")
                    for block in content
                )
                assert not has_image, "Text pages should not produce image_url blocks"
                assert has_page_text, "Text pages should include the page text in a text block"

                # Should use text-only schema (no page_transcriptions required)
                schema = call_args.kwargs.get("json_schema")
                assert "page_transcriptions" not in schema.get("properties", schema.get("required", []))

    @pytest.mark.asyncio
    async def test_examine_batch_image_page(self, agent):
        """A page with image (no text) should produce an image_url content block."""
        page_images = [(1, b"fake-jpeg-bytes", None)]

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (MOCK_BATCH_RESULT, {"input_tokens": 200, "output_tokens": 100})
                await agent.examine_batch(page_images)

                call_args = mock_call.call_args
                messages = call_args.kwargs.get("messages") or call_args[1] if len(call_args[1]) > 1 else call_args.kwargs["messages"]
                content = messages[0]["content"]

                has_image = any(
                    block.get("type") == "image_url" for block in content
                )
                assert has_image, "Image pages should produce image_url blocks"

                # Should use full schema (with page_transcriptions)
                schema = call_args.kwargs.get("json_schema")
                assert "page_transcriptions" in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_examine_batch_mixed(self, agent):
        """A batch with both text and image pages should produce the correct mix."""
        page_images = [
            (1, None, "Embedded text content for page one with sufficient length."),
            (2, b"fake-jpeg-bytes", None),
            (3, None, "More embedded text for page three with enough content here."),
        ]

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (MOCK_BATCH_RESULT, {"input_tokens": 300, "output_tokens": 150})
                await agent.examine_batch(page_images)

                call_args = mock_call.call_args
                messages = call_args.kwargs.get("messages") or call_args[1] if len(call_args[1]) > 1 else call_args.kwargs["messages"]
                content = messages[0]["content"]

                image_blocks = [b for b in content if b.get("type") == "image_url"]
                text_blocks = [b for b in content if b.get("type") == "text"]

                assert len(image_blocks) == 1, "Should have exactly 1 image block (page 2)"
                # Text blocks: context instruction + 3 page headers + 2 text page contents = 6
                assert len(text_blocks) >= 5, "Should have text blocks for headers and text pages"


class TestContextCaching:
    """Test Gemini context caching integration."""

    @pytest.mark.asyncio
    async def test_cached_call_used_when_available(self, agent):
        """When context cache is available, examine_batch should use cached call."""
        page_images = [(1, b"fake-jpeg-bytes", None)]

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value="cachedContents/test123"):
            with patch.object(agent, "call_json_structured_cached", new_callable=AsyncMock) as mock_cached:
                mock_cached.return_value = (MOCK_BATCH_RESULT, {"input_tokens": 100, "output_tokens": 50})
                result = await agent.examine_batch(page_images)

                mock_cached.assert_called_once()
                assert result.sections[0].section_type == "schedule_a"

    @pytest.mark.asyncio
    async def test_falls_back_to_uncached_on_failure(self, agent):
        """If cached call fails, should fall back to regular call_json_structured."""
        page_images = [(1, b"fake-jpeg-bytes", None)]

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value="cachedContents/test123"):
            with patch.object(agent, "call_json_structured_cached", new_callable=AsyncMock, side_effect=RuntimeError("cache error")):
                with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_uncached:
                    mock_uncached.return_value = (MOCK_BATCH_RESULT, {"input_tokens": 200, "output_tokens": 100})
                    result = await agent.examine_batch(page_images)

                    mock_uncached.assert_called_once()
                    assert result.sections[0].section_type == "schedule_a"

    @pytest.mark.asyncio
    async def test_uncached_when_cache_unavailable(self, agent):
        """When context cache is not available, should use regular call."""
        page_images = [(1, b"fake-jpeg-bytes", None)]

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (MOCK_BATCH_RESULT, {"input_tokens": 200, "output_tokens": 100})
                result = await agent.examine_batch(page_images)

                mock_call.assert_called_once()


class TestSystemPromptAndTool:
    """Test that system prompt and tool schema are well-formed."""

    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_section_types(self):
        for st in ["schedule_a", "schedule_b1", "schedule_b2", "schedule_c", "legal_description", "endorsements"]:
            assert st in SYSTEM_PROMPT

    def test_system_prompt_mentions_extraction_types(self):
        for et in ["parties", "properties", "requirement", "exception", "endorsement", "policy_info"]:
            assert et in SYSTEM_PROMPT

    def test_system_prompt_mentions_flag_types(self):
        for ft in ["missing_endorsement", "unacceptable_exception", "unresolved_lien",
                    "cross_section_mismatch", "requirement_missing_proof"]:
            assert ft in SYSTEM_PROMPT

    def test_tool_schema_valid(self):
        schema = SUBMIT_EXAMINATION_RESULTS_TOOL
        assert schema["name"] == "submit_examination_results"
        assert "input_schema" in schema
        props = schema["input_schema"]["properties"]
        assert "page_transcriptions" in props
        assert "sections" in props
        # Typed extraction arrays instead of single "extractions"
        assert "parties" in props
        assert "properties" in props
        assert "requirements" in props
        assert "exceptions" in props
        assert "endorsements" in props
        assert "policy_info_items" in props
        assert "compliance_items" in props
        assert "chain_of_title_items" in props
        assert "flags" in props

    def test_tool_schema_enum_values(self):
        props = SUBMIT_EXAMINATION_RESULTS_TOOL["input_schema"]["properties"]
        section_enum = props["sections"]["items"]["properties"]["section_type"]["enum"]
        assert "schedule_a" in section_enum
        assert "schedule_b1" in section_enum

        flag_enum = props["flags"]["items"]["properties"]["flag_type"]["enum"]
        assert "unresolved_lien" in flag_enum
        assert "missing_endorsement" in flag_enum

    def test_typed_extraction_schemas_have_correct_value_fields(self):
        """Each typed extraction array should have type-specific value fields."""
        props = EXAMINATION_JSON_SCHEMA["properties"]
        # Party schema should have name, role, etc.
        party_value_props = props["parties"]["items"]["properties"]["value"]["properties"]
        assert "name" in party_value_props
        assert "role" in party_value_props
        assert "entity_type" in party_value_props

        # Property schema should have address, apn, etc.
        prop_value_props = props["properties"]["items"]["properties"]["value"]["properties"]
        assert "address" in prop_value_props
        assert "apn" in prop_value_props
        assert "legal_description" in prop_value_props

        # Chain of title should have grantor, grantee, etc.
        chain_value_props = props["chain_of_title_items"]["items"]["properties"]["value"]["properties"]
        assert "grantor" in chain_value_props
        assert "grantee" in chain_value_props
        assert "recording_date" in chain_value_props

    def test_text_only_schema_has_no_transcriptions(self):
        """Text-only schema should not require page_transcriptions."""
        assert "page_transcriptions" not in EXAMINATION_JSON_SCHEMA_TEXT_ONLY["properties"]
        assert "page_transcriptions" not in EXAMINATION_JSON_SCHEMA_TEXT_ONLY["required"]

    def test_full_schema_has_transcriptions(self):
        """Full schema should require page_transcriptions."""
        assert "page_transcriptions" in EXAMINATION_JSON_SCHEMA["properties"]
        assert "page_transcriptions" in EXAMINATION_JSON_SCHEMA["required"]

    def test_evidence_ref_has_max_length(self):
        """Evidence ref text_snippet should have maxLength to limit output bloat."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import _EVIDENCE_REF_SCHEMA
        assert _EVIDENCE_REF_SCHEMA["properties"]["text_snippet"].get("maxLength") == 200

    def test_text_only_schema_has_typed_arrays(self):
        """Text-only schema should have typed extraction arrays."""
        props = EXAMINATION_JSON_SCHEMA_TEXT_ONLY["properties"]
        for key in TYPED_EXTRACTION_KEYS:
            assert key in props, f"Text-only schema missing {key}"

    def test_full_schema_has_typed_arrays(self):
        """Full schema should have typed extraction arrays."""
        props = EXAMINATION_JSON_SCHEMA["properties"]
        for key in TYPED_EXTRACTION_KEYS:
            assert key in props, f"Full schema missing {key}"


class TestTypedArrayParsing:
    """Test _parse_batch_result with typed extraction arrays."""

    TYPED_BATCH_RESULT = {
        "page_transcriptions": [
            {"page_number": 1, "text": "COMMITMENT FOR TITLE INSURANCE"},
        ],
        "sections": [
            {"section_type": "schedule_a", "start_page": 1, "end_page": 1, "confidence": 0.95},
        ],
        "parties": [
            {
                "label": "Buyer",
                "value": {"name": "John Doe", "role": "buyer", "entity_type": "individual",
                          "marital_status": "married", "deceased": False, "date_of_death": ""},
                "evidence_refs": [{"page_number": 1, "text_snippet": "Buyer: John Doe"}],
                "confidence": 0.95,
            },
        ],
        "properties": [
            {
                "label": "Subject Property",
                "value": {"address": "123 Main St", "apn": "001-002-003", "county": "Travis",
                          "state": "TX", "legal_description": "Lot 1 Block A", "lot": "1",
                          "block": "A", "subdivision": "Oak Hills"},
                "evidence_refs": [{"page_number": 1, "text_snippet": "123 Main St"}],
                "confidence": 0.9,
            },
        ],
        "requirements": [],
        "exceptions": [],
        "endorsements": [],
        "policy_info_items": [
            {
                "label": "Effective Date",
                "value": {"field_name": "effective_date", "field_value": "2024-01-15"},
                "evidence_refs": [{"page_number": 1, "text_snippet": "Effective: Jan 15, 2024"}],
                "confidence": 0.9,
            },
        ],
        "compliance_items": [],
        "chain_of_title_items": [
            {
                "label": "Warranty Deed 2020",
                "value": {"document_type": "warranty_deed", "grantor": "Smith",
                          "grantee": "Doe", "recording_date": "2020-05-01",
                          "recording_reference": "Vol 100 Pg 50", "consideration": "$250,000"},
                "evidence_refs": [{"page_number": 1, "text_snippet": "Warranty Deed"}],
                "confidence": 0.88,
            },
        ],
        "flags": [],
    }

    def test_parse_typed_arrays(self, agent):
        """Typed arrays should flatten into unified ExaminerExtraction list."""
        result = agent._parse_batch_result(self.TYPED_BATCH_RESULT)
        assert len(result.page_transcriptions) == 1
        assert len(result.sections) == 1

        # Should have 3 extractions: 1 party + 1 property + 1 policy_info + 1 chain_of_title
        assert len(result.extractions) == 4

        types = {e.extraction_type for e in result.extractions}
        assert types == {"party", "property", "policy_info", "chain_of_title"}

        # Check party extraction
        party = next(e for e in result.extractions if e.extraction_type == "party")
        assert party.label == "Buyer"
        assert party.value["name"] == "John Doe"
        assert party.value["role"] == "buyer"
        assert party.confidence == 0.95

        # Check chain of title extraction
        chain = next(e for e in result.extractions if e.extraction_type == "chain_of_title")
        assert chain.value["grantor"] == "Smith"
        assert chain.value["grantee"] == "Doe"

    def test_parse_legacy_extractions_backward_compat(self, agent):
        """Legacy 'extractions' key should still be parsed."""
        result = agent._parse_batch_result(MOCK_BATCH_RESULT)
        assert len(result.extractions) == 1
        assert result.extractions[0].extraction_type == "policy_info"

    def test_parse_mixed_typed_and_legacy(self, agent):
        """Both typed arrays and legacy extractions should merge."""
        raw = {
            "parties": [
                {
                    "label": "Seller",
                    "value": {"name": "Jane Smith", "role": "seller", "entity_type": "individual",
                              "marital_status": "", "deceased": False, "date_of_death": ""},
                    "confidence": 0.9,
                },
            ],
            "properties": [],
            "requirements": [],
            "exceptions": [],
            "endorsements": [],
            "policy_info_items": [],
            "compliance_items": [],
            "chain_of_title_items": [],
            "extractions": [
                {
                    "extraction_type": "policy_info",
                    "label": "Commitment Number",
                    "value": {"field_name": "commitment_number", "field_value": "T-12345"},
                    "confidence": 0.85,
                },
            ],
            "sections": [],
            "flags": [],
        }
        result = agent._parse_batch_result(raw)
        assert len(result.extractions) == 2
        types = {e.extraction_type for e in result.extractions}
        assert types == {"party", "policy_info"}

    def test_parse_empty_typed_arrays(self, agent):
        """Empty typed arrays should produce no extractions."""
        raw = {
            "parties": [],
            "properties": [],
            "requirements": [],
            "exceptions": [],
            "endorsements": [],
            "policy_info_items": [],
            "compliance_items": [],
            "chain_of_title_items": [],
            "sections": [],
            "flags": [],
        }
        result = agent._parse_batch_result(raw)
        assert len(result.extractions) == 0


class TestMaxOutputTokens:
    """Test max_output_tokens uses configured value."""

    @pytest.mark.asyncio
    async def test_pdf_batch_uses_configured_max_tokens(self, agent):
        """All batches should use the configured EXAMINER_MAX_OUTPUT_TOKENS."""
        from unittest.mock import AsyncMock, patch, MagicMock

        pdf_bytes = b"%PDF-fake"

        # Force Claude provider to test the 64000 cap
        agent._provider = "claude"

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (
                    {"page_transcriptions": [], "sections": [], "extractions": [], "flags": []},
                    {"input_tokens": 100, "output_tokens": 50},
                )
                with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
                    mock_settings.return_value = MagicMock(
                        EXAMINER_MAX_OUTPUT_TOKENS=65536,
                        EXAMINER_CALL_TIMEOUT=300,
                    )
                    # Small batch (5 pages): adaptive = max(8192, 5*2000) = 10000
                    # Capped by min(adaptive, configured_max, claude_limit)
                    await agent.examine_pdf_batch(pdf_bytes, (1, 5), 100, 0, 5)
                    call_kwargs = mock_call.call_args.kwargs
                    # 5-page batch: min(10000, 65536, 64000) = 10000
                    assert call_kwargs["max_tokens"] == 10000

    @pytest.mark.asyncio
    async def test_pdf_batch_respects_custom_max_tokens(self, agent):
        """Custom EXAMINER_MAX_OUTPUT_TOKENS should be respected."""
        from unittest.mock import AsyncMock, patch, MagicMock

        pdf_bytes = b"%PDF-fake"

        with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
            with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = (
                    {"page_transcriptions": [], "sections": [], "extractions": [], "flags": []},
                    {"input_tokens": 100, "output_tokens": 50},
                )
                with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
                    mock_settings.return_value = MagicMock(
                        EXAMINER_MAX_OUTPUT_TOKENS=16384,
                        EXAMINER_CALL_TIMEOUT=300,
                    )
                    await agent.examine_pdf_batch(pdf_bytes, (1, 20), 100, 0, 5)
                    call_kwargs = mock_call.call_args.kwargs
                    assert call_kwargs["max_tokens"] == 16384


class TestRateLimitRecovery:
    """Test RateLimitController aggressive recovery."""

    def test_initial_backoff_reduced(self):
        """First rate limit hit should use 2s base backoff, not 5s."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

        ctrl = RateLimitController(max_concurrency=5)
        backoff = ctrl.record_rate_limit()
        assert backoff == 2.0  # 2.0 * 2^0 = 2.0

    def test_backoff_cap_reduced(self):
        """Backoff should cap at 30s, not 60s."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

        ctrl = RateLimitController(max_concurrency=5)
        # 5 hits: 2, 4, 8, 16, 30 (capped)
        for _ in range(5):
            backoff = ctrl.record_rate_limit()
        assert backoff == 30.0

    def test_record_success_decrements_hits(self):
        """After 2 consecutive successes, rate_limit_hits should decrement."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

        ctrl = RateLimitController(max_concurrency=5)
        ctrl.record_rate_limit()  # hits=1
        ctrl.record_rate_limit()  # hits=2
        assert ctrl.rate_limit_hits == 2

        ctrl.record_success()  # consecutive=1
        assert ctrl.rate_limit_hits == 2  # no change yet

        ctrl.record_success()  # consecutive=2, decrements
        assert ctrl.rate_limit_hits == 1

        ctrl.record_success()  # consecutive=1 (reset after decrement)
        ctrl.record_success()  # consecutive=2, decrements
        assert ctrl.rate_limit_hits == 0

    def test_record_success_no_underflow(self):
        """rate_limit_hits should not go below 0."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

        ctrl = RateLimitController(max_concurrency=5)
        # No rate limit hits — successes should be harmless
        ctrl.record_success()
        ctrl.record_success()
        assert ctrl.rate_limit_hits == 0

    def test_rate_limit_resets_consecutive_successes(self):
        """A rate limit hit should reset the consecutive success counter."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import RateLimitController

        ctrl = RateLimitController(max_concurrency=5)
        ctrl.record_rate_limit()  # hits=1
        ctrl.record_success()  # consecutive=1
        ctrl.record_rate_limit()  # hits=2, resets consecutive to 0
        assert ctrl._consecutive_successes == 0
        assert ctrl.rate_limit_hits == 2
