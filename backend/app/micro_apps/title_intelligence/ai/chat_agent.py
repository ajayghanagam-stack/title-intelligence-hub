"""Chat agent with tool-calling pattern matching V2.

Uses search_text, get_extractions_by_type, get_flags, read_page_ocr tools.
Max 8 tool calls per interaction.
Supports both standard and streaming responses.
"""

import re
import uuid
import json
import logging
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base_service import BaseAIService
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

    SYSTEM_PROMPT = """You are a title insurance expert assistant.
You have tools to search the document, read specific pages, get extractions, and check flags.

When answering questions:
1. Use search_text to find relevant passages
2. Use read_page_ocr to read specific pages for detailed context
3. Use get_extractions_by_type to get structured data
4. Use get_flags to check risk flags

Always cite your sources by referencing page numbers in [Page X] format.
If the answer isn't in the available data, say so clearly.
Be concise and professional."""

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
            "content": f"{question}\n\nUse tools to search for relevant information, then answer. Cite page numbers in [Page X] format.",
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
        """Stream answer with tool-calling for context gathering, then streaming text.

        Yields SSE-compatible chunks: {"type": "chunk"|"done"|"error", "content": "..."}
        """
        # First, gather context via tool calls (non-streaming)
        db_handlers = create_db_tool_handlers(db, self.org_id, pack_id)
        storage_handlers = create_storage_tool_handlers(db, self.org_id, pack_id, storage)
        search_handlers = create_search_tool_handlers(db, self.org_id, pack_id)
        all_handlers = {**db_handlers, **storage_handlers, **search_handlers}

        tools = [SEARCH_TEXT_TOOL, GET_EXTRACTIONS_BY_TYPE_TOOL, GET_FLAGS_TOOL, READ_PAGE_OCR_TOOL]

        # Build initial messages
        messages = []
        if history:
            for msg in history[-8:]:
                messages.append({"role": msg.role, "content": msg.content})

        messages.append({
            "role": "user",
            "content": f"{question}\n\nUse tools to search for relevant information, then answer. Cite page numbers in [Page X] format.",
        })

        # Do tool-calling phase (non-streaming) to gather context
        import litellm
        converted_tools = _convert_tools_for_litellm(tools)
        working_messages = [{"role": "system", "content": self.SYSTEM_PROMPT}] + list(messages)

        # Tool-calling loop (max 6 steps for context, leaving room for final response)
        for step in range(6):
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=working_messages,
                    tools=converted_tools,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.error("Chat tool-calling step failed", exc_info=True)
                yield {"type": "error", "content": "An error occurred while processing your request"}
                return

            message = response.choices[0].message
            if not message.tool_calls:
                # No tool calls — stream the final response instead
                break

            working_messages.append(message.model_dump())
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments) if isinstance(
                        tool_call.function.arguments, str) else tool_call.function.arguments
                except json.JSONDecodeError:
                    args = {}

                handler = all_handlers.get(tool_name)
                if handler:
                    try:
                        result = await handler(**args)
                        result_str = json.dumps(result) if not isinstance(result, str) else result
                    except Exception as e:
                        result_str = json.dumps({"error": str(e)})
                else:
                    result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })
        else:
            # If we exhausted tool steps, the last message content is the answer
            if message and message.content:
                yield {"type": "chunk", "content": message.content}
                yield {"type": "done", "content": ""}
                return

        # Now stream the final response
        # Must include tools= if working_messages contains tool calls/results
        try:
            stream_response = await litellm.acompletion(
                model=self.model,
                messages=working_messages,
                tools=converted_tools,
                max_tokens=2048,
                stream=True,
            )
            full_text = ""
            async for chunk in stream_response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_text += delta.content
                    yield {"type": "chunk", "content": delta.content}

            yield {"type": "done", "content": ""}
        except Exception as e:
            logger.error("Chat streaming failed", exc_info=True)
            yield {"type": "error", "content": "An error occurred while generating the response"}

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
