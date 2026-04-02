"""Tests for Phase 5: Schema-First Specialized Extraction Routing."""

import uuid
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


# --- Triage doc_type_hint tests ---


class TestTriageDocTypeHints:
    """Test triage agent doc_type_hint output."""

    def test_valid_doc_types_set(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import VALID_DOC_TYPES
        expected = {
            "commitment", "deed", "mortgage", "lien", "release",
            "easement", "plat", "endorsement", "generic",
        }
        assert VALID_DOC_TYPES == expected

    def test_triage_schema_includes_doc_type(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TRIAGE_JSON_SCHEMA
        page_props = TRIAGE_JSON_SCHEMA["properties"]["pages"]["items"]["properties"]
        assert "document_type_hint" in page_props
        assert "enum" in page_props["document_type_hint"]

    def test_triage_page_result_has_doc_type(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TriagePageResult
        result = TriagePageResult(page_number=1)
        assert result.document_type_hint == "generic"

    def test_triage_page_result_custom_doc_type(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TriagePageResult
        result = TriagePageResult(page_number=1, page_type="content", document_type_hint="deed")
        assert result.document_type_hint == "deed"

    def test_parse_result_with_doc_type_hints(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TriageAgent
        agent = TriageAgent(TEST_ORG_ID)
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "content", "document_type_hint": "commitment"},
                {"page_number": 2, "page_type": "content", "document_type_hint": "deed"},
                {"page_number": 3, "page_type": "blank", "document_type_hint": "generic"},
            ]
        }
        result = agent._parse_result(raw, 3, 1.0, {})
        assert result.pages[0].document_type_hint == "commitment"
        assert result.pages[1].document_type_hint == "deed"
        assert result.pages[2].document_type_hint == "generic"

    def test_parse_result_invalid_doc_type_defaults_to_generic(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TriageAgent
        agent = TriageAgent(TEST_ORG_ID)
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "content", "document_type_hint": "invalid_type"},
            ]
        }
        result = agent._parse_result(raw, 1, 1.0, {})
        assert result.pages[0].document_type_hint == "generic"

    def test_parse_result_missing_doc_type_defaults_to_generic(self):
        from app.micro_apps.title_intelligence.ai.triage_agent import TriageAgent
        agent = TriageAgent(TEST_ORG_ID)
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "content"},
            ]
        }
        result = agent._parse_result(raw, 1, 1.0, {})
        assert result.pages[0].document_type_hint == "generic"


# --- Document grouper doc_type tests ---


class TestGrouperDocType:
    """Test document grouper doc_type assignment."""

    def test_group_pages_with_doc_type_hints(self):
        from app.micro_apps.title_intelligence.services.document_grouper import group_pages
        pages = [
            {"page_number": 1, "page_type": "content", "document_type_hint": "deed"},
            {"page_number": 2, "page_type": "content", "document_type_hint": "deed"},
            {"page_number": 3, "page_type": "blank"},
            {"page_number": 4, "page_type": "content", "document_type_hint": "mortgage"},
        ]
        result = group_pages(pages)
        assert len(result.groups) == 2
        assert result.groups[0].doc_type == "deed"
        assert result.groups[1].doc_type == "mortgage"

    def test_majority_vote_doc_type(self):
        from app.micro_apps.title_intelligence.services.document_grouper import group_pages
        pages = [
            {"page_number": 1, "page_type": "content", "document_type_hint": "deed"},
            {"page_number": 2, "page_type": "content", "document_type_hint": "deed"},
            {"page_number": 3, "page_type": "content", "document_type_hint": "mortgage"},
        ]
        result = group_pages(pages)
        assert len(result.groups) == 1
        assert result.groups[0].doc_type == "deed"

    def test_all_generic_hints_gives_generic(self):
        from app.micro_apps.title_intelligence.services.document_grouper import group_pages
        pages = [
            {"page_number": 1, "page_type": "content", "document_type_hint": "generic"},
            {"page_number": 2, "page_type": "content", "document_type_hint": "generic"},
        ]
        result = group_pages(pages)
        assert result.groups[0].doc_type == "generic"

    def test_no_doc_type_hint_defaults_to_generic(self):
        from app.micro_apps.title_intelligence.services.document_grouper import group_pages
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "content"},
        ]
        result = group_pages(pages)
        assert result.groups[0].doc_type == "generic"

    def test_specific_hint_beats_generic(self):
        from app.micro_apps.title_intelligence.services.document_grouper import group_pages
        pages = [
            {"page_number": 1, "page_type": "content", "document_type_hint": "generic"},
            {"page_number": 2, "page_type": "content", "document_type_hint": "lien"},
            {"page_number": 3, "page_type": "content", "document_type_hint": "generic"},
        ]
        result = group_pages(pages)
        # "lien" is the only specific type, so it wins
        assert result.groups[0].doc_type == "lien"

    def test_groups_to_doc_types(self):
        from app.micro_apps.title_intelligence.services.document_grouper import (
            group_pages,
            groups_to_doc_types,
        )
        pages = [
            {"page_number": 1, "page_type": "content", "document_type_hint": "deed"},
            {"page_number": 2, "page_type": "blank"},
            {"page_number": 3, "page_type": "content", "document_type_hint": "mortgage"},
        ]
        result = group_pages(pages)
        doc_types = groups_to_doc_types(result.groups)
        assert doc_types == ["deed", "mortgage"]

    def test_remap_preserves_doc_type(self):
        from app.micro_apps.title_intelligence.services.document_grouper import (
            DocumentGroup,
            remap_groups_to_filtered_pdf,
        )
        groups = [
            DocumentGroup(group_id=0, start_page=2, end_page=3, page_count=2, pages=[2, 3], doc_type="deed"),
        ]
        inverse_map = {2: 1, 3: 2}
        remapped = remap_groups_to_filtered_pdf(groups, inverse_map)
        assert remapped[0].doc_type == "deed"


class TestResolveDocType:
    """Test the _resolve_doc_type helper."""

    def test_empty_hints(self):
        from app.micro_apps.title_intelligence.services.document_grouper import _resolve_doc_type
        assert _resolve_doc_type([]) == "generic"

    def test_all_generic(self):
        from app.micro_apps.title_intelligence.services.document_grouper import _resolve_doc_type
        assert _resolve_doc_type(["generic", "generic"]) == "generic"

    def test_single_specific(self):
        from app.micro_apps.title_intelligence.services.document_grouper import _resolve_doc_type
        assert _resolve_doc_type(["deed"]) == "deed"

    def test_majority_wins(self):
        from app.micro_apps.title_intelligence.services.document_grouper import _resolve_doc_type
        assert _resolve_doc_type(["deed", "deed", "mortgage"]) == "deed"

    def test_specific_beats_generic(self):
        from app.micro_apps.title_intelligence.services.document_grouper import _resolve_doc_type
        assert _resolve_doc_type(["generic", "lien", "generic"]) == "lien"


# --- Extraction registry tests ---


class TestExtractionRegistry:
    """Test the extraction config registry."""

    def test_all_doc_types_have_configs(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import (
            get_extraction_config,
            list_doc_types,
        )
        for dt in list_doc_types():
            config = get_extraction_config(dt)
            assert config.doc_type == dt
            assert len(config.system_prompt) > 0
            assert "properties" in config.json_schema

    def test_generic_fallback(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        config = get_extraction_config("generic")
        assert config.doc_type == "generic"
        # Generic should have the full examiner prompt
        assert "schedule_a" in config.system_prompt.lower() or "extract" in config.system_prompt.lower()

    def test_unknown_doc_type_falls_back_to_generic(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        config = get_extraction_config("totally_unknown")
        assert config.doc_type == "generic"

    def test_commitment_config_has_schedule_sections(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        config = get_extraction_config("commitment")
        schema = config.json_schema
        section_items = schema["properties"]["sections"]["items"]
        section_enum = section_items["properties"]["section_type"]["enum"]
        assert "schedule_a" in section_enum
        assert "schedule_b1" in section_enum

    def test_deed_config_has_chain_of_title(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        config = get_extraction_config("deed")
        schema = config.json_schema
        # Typed arrays: chain_of_title_items and parties should be present
        assert "chain_of_title_items" in schema["properties"]
        assert "parties" in schema["properties"]

    def test_mortgage_config_has_unreleased_flag(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        config = get_extraction_config("mortgage")
        schema = config.json_schema
        flag_items = schema["properties"]["flags"]["items"]
        flag_enum = flag_items["properties"]["flag_type"]["enum"]
        assert "unreleased_mortgage" in flag_enum

    def test_specialized_prompts_shorter_than_generic(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
        generic = get_extraction_config("generic")
        for dt in ["deed", "mortgage", "lien", "release", "easement", "plat", "endorsement"]:
            specialized = get_extraction_config(dt)
            assert len(specialized.system_prompt) < len(generic.system_prompt), (
                f"{dt} prompt ({len(specialized.system_prompt)}) should be shorter "
                f"than generic ({len(generic.system_prompt)})"
            )

    def test_registry_hash_deterministic(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import compute_registry_hash
        h1 = compute_registry_hash()
        h2 = compute_registry_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_list_doc_types(self):
        from app.micro_apps.title_intelligence.ai.extractors.registry import list_doc_types
        types = list_doc_types()
        assert "deed" in types
        assert "mortgage" in types
        assert "commitment" in types
        assert "generic" not in types  # generic is not a specialized type

    def test_all_schemas_have_required_keys(self):
        """Every schema should have page_transcriptions, sections, typed extraction arrays, flags."""
        from app.micro_apps.title_intelligence.ai.extractors.registry import (
            get_extraction_config,
            list_doc_types,
        )
        for dt in list_doc_types():
            config = get_extraction_config(dt)
            props = config.json_schema.get("properties", {})
            assert "page_transcriptions" in props, f"{dt} missing page_transcriptions"
            assert "sections" in props, f"{dt} missing sections"
            assert "flags" in props, f"{dt} missing flags"
            # Should have at least one typed extraction array
            typed_keys = {"parties", "properties", "requirements", "exceptions",
                          "endorsements", "policy_info_items", "compliance_items",
                          "chain_of_title_items"}
            found = typed_keys & set(props.keys())
            assert len(found) > 0, f"{dt} has no typed extraction arrays"


# --- Examiner routing integration tests ---


class TestExaminerRouting:
    """Test specialized routing in examine_document_native_pdf."""

    @pytest.mark.asyncio
    async def test_chunk_doc_types_routes_to_specialized(self):
        """When chunk_doc_types provided, specialized configs are used."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult
        import fitz

        doc = fitz.open()
        for i in range(6):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)
        captured_overrides = []

        original_method = agent.examine_pdf_batch

        async def mock_examine_pdf_batch(
            pdf_bytes, page_range, total_pages, batch_index, total_batches,
            system_prompt_override=None, json_schema_override=None,
        ):
            captured_overrides.append({
                "batch_index": batch_index,
                "has_prompt_override": system_prompt_override is not None,
                "has_schema_override": json_schema_override is not None,
            })
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 0
            settings.SPECIALIZED_EXTRACTION_ENABLED = True
            mock_settings.return_value = settings

            await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=6,
                batch_size=3,
                concurrency=5,
                page_ranges=[(1, 3), (4, 6)],
                chunk_doc_types=["deed", "mortgage"],
            )

        assert len(captured_overrides) == 2
        # Both chunks should have specialized prompts
        for override in captured_overrides:
            assert override["has_prompt_override"] is True
            assert override["has_schema_override"] is True

    @pytest.mark.asyncio
    async def test_generic_doc_type_uses_default_prompt(self):
        """Generic doc_type should NOT override the prompt."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult
        import fitz

        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)
        captured_overrides = []

        async def mock_examine_pdf_batch(
            pdf_bytes, page_range, total_pages, batch_index, total_batches,
            system_prompt_override=None, json_schema_override=None,
        ):
            captured_overrides.append({
                "has_prompt_override": system_prompt_override is not None,
            })
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 0
            settings.SPECIALIZED_EXTRACTION_ENABLED = True
            mock_settings.return_value = settings

            await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=3,
                batch_size=3,
                concurrency=5,
                page_ranges=[(1, 3)],
                chunk_doc_types=["generic"],
            )

        assert len(captured_overrides) == 1
        # Generic should NOT have a prompt override
        assert captured_overrides[0]["has_prompt_override"] is False

    @pytest.mark.asyncio
    async def test_specialized_disabled_uses_default(self):
        """When SPECIALIZED_EXTRACTION_ENABLED=False, no overrides applied."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult
        import fitz

        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)
        captured_overrides = []

        async def mock_examine_pdf_batch(
            pdf_bytes, page_range, total_pages, batch_index, total_batches,
            system_prompt_override=None, json_schema_override=None,
        ):
            captured_overrides.append({
                "has_prompt_override": system_prompt_override is not None,
            })
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 0
            settings.SPECIALIZED_EXTRACTION_ENABLED = False
            mock_settings.return_value = settings

            await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=3,
                batch_size=3,
                concurrency=5,
                page_ranges=[(1, 3)],
                chunk_doc_types=["deed"],
            )

        assert captured_overrides[0]["has_prompt_override"] is False


# --- Version tracker integration ---


class TestVersionTrackerSpecialized:

    def test_version_info_includes_registry_hash(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
        settings = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks", PIPELINE_MODE="native_pdf", AI_PROVIDER="gemini")
        info = collect_version_info(settings)
        assert "extraction_registry_hash" in info
        assert len(info["extraction_registry_hash"]) == 64

    def test_version_info_no_registry_hash_when_disabled(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
        settings = Settings(
            DEBUG=True, PIPELINE_BACKEND="background_tasks",
            PIPELINE_MODE="native_pdf", SPECIALIZED_EXTRACTION_ENABLED=False,
        )
        info = collect_version_info(settings)
        assert info["extraction_registry_hash"] == ""

    def test_version_info_no_registry_hash_in_legacy(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
        settings = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks", PIPELINE_MODE="legacy")
        info = collect_version_info(settings)
        assert info["extraction_registry_hash"] == ""

    def test_version_metadata_includes_specialized_flag(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info
        settings = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks")
        info = collect_version_info(settings)
        assert "specialized_extraction" in info["version_metadata"]

    def test_cache_key_changes_with_registry(self):
        """Extraction registry hash should affect the cache key."""
        from app.micro_apps.title_intelligence.pipeline.version_tracker import compute_examiner_cache_key
        base = {
            "ai_model": "test",
            "ingestion_prompt_hash": "p1",
            "extraction_tool_hash": "t1",
            "rules_version": "v1",
            "triage_prompt_hash": "tp1",
            "extraction_registry_hash": "reg1",
        }
        key1 = compute_examiner_cache_key("file_hash", base)
        modified = {**base, "extraction_registry_hash": "reg2"}
        key2 = compute_examiner_cache_key("file_hash", modified)
        assert key1 != key2


# --- Config test ---


class TestConfigSpecialized:

    def test_specialized_extraction_default(self):
        from app.config import Settings
        s = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks")
        assert s.SPECIALIZED_EXTRACTION_ENABLED is True

    def test_specialized_extraction_disabled(self):
        from app.config import Settings
        s = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks", SPECIALIZED_EXTRACTION_ENABLED=False)
        assert s.SPECIALIZED_EXTRACTION_ENABLED is False
