"""Chat agent with tool-calling pattern matching V2.

Uses search_text, get_extractions_by_type, get_flags, read_page_ocr tools.
Max 8 tool calls per interaction.
Supports both standard and streaming responses.
"""

import re
import uuid
import json
import logging
from typing import Any, AsyncGenerator  # noqa: F401 — Any used in stream_answer

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base_service import BaseAIService
from app.config import get_settings
from app.micro_apps.title_intelligence.ai.tools.database import (
    GET_EXTRACTIONS_BY_TYPE_TOOL, GET_FLAGS_TOOL,
    create_db_tool_handlers,
)
from app.micro_apps.title_intelligence.ai.tools.storage import (
    READ_PAGE_OCR_TOOL, create_storage_tool_handlers,
)
from app.micro_apps.title_intelligence.ai.tools.search import (
    SEARCH_TEXT_TOOL, create_search_tool_handlers,
)
from app.micro_apps.title_intelligence.services.storage import StorageProvider

logger = logging.getLogger(__name__)


class ChatAgent(BaseAIService):
    """Answer questions about a title document with citations using tools."""

    def __init__(self, org_id: uuid.UUID):
        settings = get_settings()
        provider_override = settings.TI_CHAT_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)

    SYSTEM_PROMPT = """You are a title insurance expert assistant. Your ONLY purpose is to answer questions about the specific title commitment document that has been uploaded and processed in this pack.

You have tools available to look up information from this document:
- search_text: Search the document text for relevant passages
- read_page_ocr: Read the full text of a specific page
- get_extractions_by_type: Get structured data (parties, property details, etc.)
- get_flags: Get risk flags identified during analysis

**When to use tools**: Use tools when the user asks about specific document content, parties, property details, dates, amounts, exceptions, requirements, or flags. Always search before answering document-specific questions.

**When NOT to use tools**: For greetings or clarifications about your previous answers — just respond directly.

**IMPORTANT RULES**:
- ONLY answer questions about this specific document. Do NOT answer questions about other documents, outside topics, or general knowledge.
- If asked about something not covered in this document, politely decline and explain that you can only assist with questions about the uploaded title commitment.
- When citing document information, reference page numbers in [Page X] format. Only cite page numbers that actually exist in this document.
- Be concise and professional."""

    async def answer_with_tools(
        self,
        db: AsyncSession,
        pack_id: uuid.UUID,
        storage: StorageProvider,
        question: str,
        history: list | None = None,
    ) -> tuple[str, list[dict]]:
        """Answer a question using tool-calling.

        Returns: (answer_text, citations_list)
        """
        db_handlers = create_db_tool_handlers(db, self.org_id, pack_id)
        storage_handlers = create_storage_tool_handlers(db, self.org_id, pack_id, storage)
        search_handlers = create_search_tool_handlers(db, self.org_id, pack_id)
        all_handlers = {**db_handlers, **storage_handlers, **search_handlers}

        tools = [
            SEARCH_TEXT_TOOL,
            GET_EXTRACTIONS_BY_TYPE_TOOL,
            GET_FLAGS_TOOL,
            READ_PAGE_OCR_TOOL,
        ]

        # Build messages with history
        messages = []
        if history:
            for msg in history[-8:]:
                messages.append({"role": msg.role, "content": msg.content})

        messages.append({
            "role": "user",
            "content": question,
        })

        result = await self.call_with_tools(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            tool_handlers=all_handlers,
            max_steps=8,
            max_tokens=2048,
        )

        response_text = result.get("text", "")
        citations = _extract_citations_from_text(response_text)

        return response_text, citations

    async def stream_answer(
        self,
        db: AsyncSession,
        pack_id: uuid.UUID,
        storage: StorageProvider,
        question: str,
        history: list | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Answer with tools, then yield the result as SSE chunks.

        Yields: {"type": "chunk"|"done"|"error", "content": "..."}

        Uses the proven call_with_tools() for the tool loop, then yields
        the final text. Single code path, no fragile streaming-tool parsing.
        """
        try:
            response_text, _ = await self.answer_with_tools(
                db=db, pack_id=pack_id, storage=storage,
                question=question, history=history,
            )
        except Exception:
            logger.error("Chat answer_with_tools failed", exc_info=True)
            yield {"type": "error", "content": "An error occurred while processing your request"}
            return

        if response_text:
            yield {"type": "chunk", "content": response_text}
        yield {"type": "done", "content": ""}

    # Keep backward-compatible answer method
    async def answer(
        self,
        question: str,
        chunks: list,
        extractions: list,
        history: list,
    ) -> tuple[str, list[dict]]:
        """Legacy answer method — still works for backward compatibility."""
        chunk_text = "\n".join(
            f"[Page {c.page_number}] {c.content}" for c in chunks
        ) if chunks else "No relevant text chunks found."

        extraction_text = "\n".join(
            f"- [{e.extraction_type}] {e.label}: {e.value}" for e in extractions
        ) if extractions else "No extractions available."

        context = f"Relevant text passages:\n{chunk_text}\n\nExtractions:\n{extraction_text}"

        messages = []
        for msg in history[-8:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer and cite page numbers in [Page X] format.",
        })

        response = await self.call_haiku(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            max_tokens=2048,
        )

        citations = _extract_citations(response, chunks)
        return response, citations


def _extract_citations_from_text(response: str) -> list[dict]:
    """Parse [Page X] references from the response text."""
    citations = []
    seen_pages = set()
    for match in re.finditer(r"\[Page\s+(\d+)\]", response):
        page_num = int(match.group(1))
        if page_num not in seen_pages:
            seen_pages.add(page_num)
            citations.append({"page_number": page_num, "text_snippet": ""})
    return citations


def _extract_citations(response: str, chunks: list) -> list[dict]:
    """Parse [Page X] references from the response (legacy with chunk lookup)."""
    citations = []
    seen_pages = set()
    for match in re.finditer(r"\[Page\s+(\d+)\]", response):
        page_num = int(match.group(1))
        if page_num not in seen_pages:
            seen_pages.add(page_num)
            snippet = ""
            for c in chunks:
                if c.page_number == page_num:
                    snippet = c.content[:200]
                    break
            citations.append({"page_number": page_num, "text_snippet": snippet})
    return citations


def _convert_tools_for_litellm(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tools to OpenAI/litellm format."""
    converted = []
    for tool in tools:
        if "input_schema" in tool:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
        else:
            converted.append(tool)
    return converted
