"""Ingestion agent with tool-calling pattern matching V2.

Two modes:
- Prefetched (small docs): All OCR text in prompt, uses create_sections/create_extractions tools
- Interactive (large docs): Reads pages via tools, creates records via tools
"""

import uuid
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base_service import BaseAIService
from app.micro_apps.title_intelligence.ai.tools.database import (
    GET_PACK_FILES_TOOL, CREATE_SECTIONS_TOOL, CREATE_EXTRACTIONS_TOOL,
    DELETE_SECTIONS_TOOL, DELETE_EXTRACTIONS_TOOL,
    create_db_tool_handlers,
)
from app.micro_apps.title_intelligence.ai.tools.storage import (
    READ_PAGE_RANGE_TOOL, create_storage_tool_handlers,
)
from app.micro_apps.title_intelligence.services.storage import StorageProvider

logger = logging.getLogger(__name__)

# Maximum characters of OCR text to send in one call (prefetched mode)
MAX_TEXT_PER_CALL = 80000


class IngestionAgent(BaseAIService):
    """Detect document sections and extract structured data using tool-calling."""

    SYSTEM_PROMPT = """You are a title insurance document analysis expert.
You have access to tools to read document pages and create structured records.

Your tasks:
1. Read through all pages of the document
2. Identify document sections (Schedule A, Schedule B-I Requirements, Schedule B-II Exceptions, Legal Description, Endorsements)
3. Extract ALL structured data you can find:
   - Parties: buyer, seller, lender, title company, underwriter
   - Property info: address, APN/parcel number, county, state, legal description summary
   - Requirements from Schedule B-I: each numbered requirement
   - Exceptions from Schedule B-II: each numbered exception
   - Endorsements: each endorsement listed
   - Policy info: commitment number, effective date, policy amount, premium

Process:
1. First, delete any existing sections and extractions (for idempotent retry)
2. Read the document pages using read_page_range
3. Create sections using create_sections
4. Create extractions using create_extractions

You MUST extract as many items as possible. Do not skip extractions.
For each extraction, provide evidence references (page number and relevant text snippet).
Assign a confidence score (0.0-1.0) based on text clarity."""

    async def analyze_with_tools(
        self,
        db: AsyncSession,
        pack_id: uuid.UUID,
        storage: StorageProvider,
        pages_text: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Analyze document using tool-calling pattern.

        Args:
            db: Database session
            pack_id: Pack ID
            storage: Storage provider
            pages_text: Optional pre-loaded page text (for prefetched mode)

        Returns: {"sections_created": int, "extractions_created": int}
        """
        # Create tool handlers
        db_handlers = create_db_tool_handlers(db, self.org_id, pack_id)
        storage_handlers = create_storage_tool_handlers(db, self.org_id, pack_id, storage)
        all_handlers = {**db_handlers, **storage_handlers}

        tools = [
            GET_PACK_FILES_TOOL,
            READ_PAGE_RANGE_TOOL,
            DELETE_SECTIONS_TOOL,
            DELETE_EXTRACTIONS_TOOL,
            CREATE_SECTIONS_TOOL,
            CREATE_EXTRACTIONS_TOOL,
        ]

        # Build initial message
        if pages_text and self._total_text_length(pages_text) <= MAX_TEXT_PER_CALL:
            # Prefetched mode — include all text in prompt
            combined = "\n\n".join(
                f"=== PAGE {p['page_number']} ===\n{p['text']}" for p in pages_text
            )
            user_message = (
                "Here is the complete document text. Analyze it, identify all sections, "
                "and extract ALL structured data. First delete existing sections/extractions, "
                "then create new ones using the tools.\n\n"
                f"{combined}"
            )
        else:
            # Interactive mode — let agent read pages via tools
            user_message = (
                "Analyze the title document. Start by getting the pack files to understand "
                "the document structure, then read pages using read_page_range to analyze the content. "
                "First delete existing sections/extractions for idempotent retry, "
                "then create sections and extractions as you find them."
            )

        messages = [{"role": "user", "content": user_message}]

        result = await self.call_with_tools(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            tool_handlers=all_handlers,
            max_steps=10,
            max_tokens=8192,
        )

        logger.info(f"Ingestion agent completed in {result.get('steps', 0)} steps")
        return result

    def _total_text_length(self, pages_text: list[dict]) -> int:
        return sum(len(p.get("text", "")) for p in pages_text)

    # Keep backward-compatible analyze method
    async def analyze(self, pages_text: list[dict]) -> dict[str, Any]:
        """Legacy analyze method — still works for backward compatibility.

        Prefer analyze_with_tools() for new code.
        """
        combined_text = "\n\n".join(
            f"=== PAGE {p['page_number']} ===\n{p['text']}" for p in pages_text
        )

        tools = [
            {
                "name": "document_analysis",
                "description": "Return detected sections and extracted data from the title document",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "section_type": {"type": "string", "enum": ["schedule_a", "schedule_b", "schedule_c", "endorsements", "legal_description"]},
                                    "start_page": {"type": "integer"},
                                    "end_page": {"type": "integer"},
                                    "confidence": {"type": "number"},
                                },
                                "required": ["section_type", "start_page", "end_page", "confidence"],
                            },
                        },
                        "extractions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "extraction_type": {"type": "string", "enum": ["party", "property_info", "requirement", "exception", "endorsement", "legal_description"]},
                                    "label": {"type": "string"},
                                    "value": {"type": "object"},
                                    "evidence_refs": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "page_number": {"type": "integer"},
                                                "text_snippet": {"type": "string"},
                                            },
                                            "required": ["page_number", "text_snippet"],
                                        },
                                    },
                                    "confidence": {"type": "number"},
                                },
                                "required": ["extraction_type", "label", "value", "evidence_refs", "confidence"],
                            },
                        },
                    },
                    "required": ["sections", "extractions"],
                },
            }
        ]

        # Handle large documents by chunking
        if len(combined_text) <= MAX_TEXT_PER_CALL:
            return await self._analyze_chunk(combined_text, tools)

        import asyncio
        logger.info(f"Document too large ({len(combined_text)} chars), splitting into chunks")
        chunks = self._build_chunks(pages_text)

        results = await asyncio.gather(
            *[self._analyze_chunk(text, tools) for text, _ in chunks]
        )

        all_sections = []
        all_extractions = []
        for result in results:
            all_sections.extend(result.get("sections", []))
            all_extractions.extend(result.get("extractions", []))

        # Deduplicate sections by type
        section_map = {}
        for s in all_sections:
            key = s["section_type"]
            if key not in section_map or s.get("confidence", 0) > section_map[key].get("confidence", 0):
                section_map[key] = s

        return {"sections": list(section_map.values()), "extractions": all_extractions}

    def _build_chunks(self, pages_text: list[dict]) -> list[tuple[str, list[int]]]:
        chunks = []
        chunk_text = ""
        chunk_pages: list[int] = []
        for p in pages_text:
            page_block = f"=== PAGE {p['page_number']} ===\n{p['text']}\n\n"
            if len(chunk_text) + len(page_block) > MAX_TEXT_PER_CALL and chunk_text:
                chunks.append((chunk_text, list(chunk_pages)))
                chunk_text = ""
                chunk_pages = []
            chunk_text += page_block
            chunk_pages.append(p["page_number"])
        if chunk_text:
            chunks.append((chunk_text, list(chunk_pages)))
        return chunks

    async def _analyze_chunk(self, text: str, tools: list) -> dict[str, Any]:
        messages = [{"role": "user", "content": f"Analyze this title document text. Extract ALL sections and ALL structured data.\n\n{text}"}]
        result = await self.call_haiku_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            max_tokens=8192,
        )
        return {"sections": result.get("sections", []), "extractions": result.get("extractions", [])}
