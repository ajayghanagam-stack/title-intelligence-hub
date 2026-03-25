"""Risk agent with tool-calling pattern matching V2.

Reads extractions, sections, and OCR text via tools. Creates flags via tools.
Analyzes every requirement and exception for potential risks.
"""

import uuid
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base_service import BaseAIService
from app.micro_apps.title_intelligence.ai.tools.database import (
    GET_EXTRACTIONS_TOOL, GET_EXTRACTIONS_BY_TYPE_TOOL, GET_SECTIONS_TOOL,
    CREATE_FLAGS_TOOL, create_db_tool_handlers,
)
from app.micro_apps.title_intelligence.ai.tools.storage import (
    READ_PAGE_RANGE_TOOL, create_storage_tool_handlers,
)
from app.micro_apps.title_intelligence.services.storage import StorageProvider

logger = logging.getLogger(__name__)


class RiskAgent(BaseAIService):
    """Analyze document for risks using iterative tool-calling."""

    SYSTEM_PROMPT = """You are a title insurance risk analysis expert.
You have tools to read extractions, sections, and document text, and to create risk flags.

Your process:
1. Get all extractions and sections to understand the document
2. Read relevant page ranges for additional context
3. Analyze every requirement and every exception for potential issues
4. Create flags for all identified risks

Flag types:
- missing_endorsement: Required endorsement not found
- unacceptable_exception: Exception that may block closing
- unresolved_lien: Lien or encumbrance not cleared
- cross_section_mismatch: Inconsistency between document sections
- requirement_missing_proof: Requirement without evidence of satisfaction

Severity levels:
- critical: Will block closing, must be resolved immediately
- high: Significant risk, should be resolved before closing
- medium: Moderate risk, should be reviewed
- low: Minor issue, informational

You MUST identify at least the most obvious risks. For each flag, provide:
- Clear title and description
- Detailed AI explanation of why this is a risk
- Evidence references (page number + relevant text snippet)"""

    async def analyze_with_tools(
        self,
        db: AsyncSession,
        pack_id: uuid.UUID,
        storage: StorageProvider,
    ) -> dict[str, Any]:
        """Analyze document for risks using tool-calling.

        Returns: {"text": str, "steps": int}
        """
        db_handlers = create_db_tool_handlers(db, self.org_id, pack_id)
        storage_handlers = create_storage_tool_handlers(db, self.org_id, pack_id, storage)
        all_handlers = {**db_handlers, **storage_handlers}

        tools = [
            GET_EXTRACTIONS_TOOL,
            GET_EXTRACTIONS_BY_TYPE_TOOL,
            GET_SECTIONS_TOOL,
            READ_PAGE_RANGE_TOOL,
            CREATE_FLAGS_TOOL,
        ]

        messages = [{
            "role": "user",
            "content": (
                "Analyze this title document for ALL risks and issues. "
                "First get the extractions and sections, then read relevant pages for context. "
                "Create flags for every risk you identify. "
                "Analyze every requirement and every exception thoroughly."
            ),
        }]

        result = await self.call_with_tools(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            tool_handlers=all_handlers,
            max_steps=20,
            max_tokens=8192,
        )

        logger.info(f"Risk agent completed in {result.get('steps', 0)} steps")
        return result

    # Keep backward-compatible analyze method
    async def analyze(
        self,
        extractions: list[dict],
        sections: list[dict],
        ocr_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Legacy analyze method — still works for backward compatibility."""
        context_parts = [
            f"Sections:\n{_format_sections(sections)}",
            f"\nExtractions:\n{_format_extractions(extractions)}",
        ]

        if ocr_text:
            truncated = ocr_text[:60000]
            context_parts.append(f"\nDocument OCR Text:\n{truncated}")

        context = "\n".join(context_parts)

        tools = [
            {
                "name": "risk_flags",
                "description": "Return identified risk flags",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "flags": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "flag_type": {"type": "string", "enum": ["missing_endorsement", "unacceptable_exception", "unresolved_lien", "cross_section_mismatch", "requirement_missing_proof"]},
                                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "ai_explanation": {"type": "string"},
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
                                },
                                "required": ["flag_type", "severity", "title", "description", "ai_explanation", "evidence_refs"],
                            },
                        },
                    },
                    "required": ["flags"],
                },
            }
        ]

        messages = [{"role": "user", "content": f"Analyze this title document data for ALL risks:\n\n{context}"}]

        result = await self.call_haiku_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            max_tokens=8192,
        )

        flags = result.get("flags", [])
        logger.info(f"Risk agent found {len(flags)} flags")
        return flags


def _format_sections(sections: list[dict]) -> str:
    lines = [f"- {s.get('section_type', 'unknown')}: pages {s.get('start_page')}-{s.get('end_page')}" for s in sections]
    return "\n".join(lines) if lines else "No sections detected"


def _format_extractions(extractions: list[dict]) -> str:
    lines = [f"- [{e.get('extraction_type', '')}] {e.get('label', '')}: {e.get('value', {})}" for e in extractions]
    return "\n".join(lines) if lines else "No extractions found"
