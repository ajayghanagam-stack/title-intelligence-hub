"""Review assistant with tool-calling pattern matching V2.

Reads flag details, extractions, and OCR via tools. Max 5 tool calls.
Returns recommendation with decision, reasoning, and confidence.
"""

import uuid
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base_service import BaseAIService
from app.micro_apps.title_intelligence.ai.tools.database import (
    GET_EXTRACTIONS_TOOL, GET_EXTRACTIONS_BY_TYPE_TOOL,
    GET_FLAGS_TOOL, GET_REVIEWS_BY_FLAG_TOOL,
    create_db_tool_handlers,
)
from app.micro_apps.title_intelligence.ai.tools.storage import (
    READ_PAGE_OCR_TOOL, create_storage_tool_handlers,
)
from app.micro_apps.title_intelligence.services.storage import StorageProvider

logger = logging.getLogger(__name__)


class ReviewAssistant(BaseAIService):
    """Generate AI recommendation for flag review decisions using tools."""

    SYSTEM_PROMPT = """You are a senior title insurance underwriter.
You have tools to read extractions, other flags, and document pages.

Given a risk flag, use the tools to gather evidence and then recommend a decision.

Decisions:
- approve: The flag identifies a legitimate concern that should be tracked
- reject: The flag is a false positive or not actually a risk
- escalate: The flag requires senior review or additional information

After gathering evidence, provide your recommendation using the review_recommendation tool."""

    async def recommend_with_tools(
        self,
        db: AsyncSession,
        pack_id: uuid.UUID,
        storage: StorageProvider,
        flag: dict,
    ) -> dict[str, Any]:
        """Generate a recommendation using tool-calling.

        Returns: {"decision": str, "reasoning": str, "confidence": float}
        """
        db_handlers = create_db_tool_handlers(db, self.org_id, pack_id)
        storage_handlers = create_storage_tool_handlers(db, self.org_id, pack_id, storage)
        all_handlers = {**db_handlers, **storage_handlers}

        # Add the recommendation output tool
        recommendation_tool = {
            "name": "review_recommendation",
            "description": "Submit your review recommendation",
            "input_schema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["approve", "reject", "escalate"]},
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["decision", "reasoning", "confidence"],
            },
        }

        # Capture recommendation from tool call
        recommendation_result = {}

        async def handle_recommendation(decision: str, reasoning: str, confidence: float, **kwargs):
            nonlocal recommendation_result
            recommendation_result = {
                "decision": decision,
                "reasoning": reasoning,
                "confidence": confidence,
            }
            return {"submitted": True}

        all_handlers["review_recommendation"] = handle_recommendation

        tools = [
            GET_EXTRACTIONS_TOOL,
            GET_EXTRACTIONS_BY_TYPE_TOOL,
            GET_FLAGS_TOOL,
            READ_PAGE_OCR_TOOL,
            recommendation_tool,
        ]

        flag_context = (
            f"Flag to review:\n"
            f"- Title: {flag.get('title', '')}\n"
            f"- Type: {flag.get('flag_type', '')}\n"
            f"- Severity: {flag.get('severity', '')}\n"
            f"- Description: {flag.get('description', '')}\n"
            f"- AI Explanation: {flag.get('ai_explanation', '')}\n"
            f"- Evidence: {flag.get('evidence_refs', [])}"
        )

        messages = [{
            "role": "user",
            "content": (
                f"{flag_context}\n\n"
                "Review this flag. Use tools to gather supporting evidence from the document, "
                "then submit your recommendation using the review_recommendation tool."
            ),
        }]

        await self.call_with_tools(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            tool_handlers=all_handlers,
            max_steps=5,
            max_tokens=2048,
        )

        if recommendation_result:
            return recommendation_result

        # Fallback if tool wasn't called
        return {
            "decision": "escalate",
            "reasoning": "Unable to determine recommendation — requires manual review",
            "confidence": 0.3,
        }

    # Keep backward-compatible recommend method
    async def recommend(
        self,
        flag: dict,
        extractions: list[dict],
    ) -> dict[str, Any]:
        """Legacy recommend method."""
        flag_context = (
            f"Flag: {flag.get('title', '')}\n"
            f"Type: {flag.get('flag_type', '')}\n"
            f"Severity: {flag.get('severity', '')}\n"
            f"Description: {flag.get('description', '')}\n"
            f"AI Explanation: {flag.get('ai_explanation', '')}\n"
            f"Evidence: {flag.get('evidence_refs', [])}"
        )

        extraction_context = "\n".join(
            f"- [{e.get('extraction_type')}] {e.get('label')}: {e.get('value')}"
            for e in extractions
        )

        tools = [{
            "name": "review_recommendation",
            "description": "Return a review recommendation",
            "input_schema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["approve", "reject", "escalate"]},
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["decision", "reasoning", "confidence"],
            },
        }]

        messages = [{
            "role": "user",
            "content": f"Review this flag and recommend a decision:\n\n{flag_context}\n\nRelated extractions:\n{extraction_context}",
        }]

        result = await self.call_haiku_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            max_tokens=1024,
        )

        return {
            "decision": result.get("decision", "escalate"),
            "reasoning": result.get("reasoning", "Unable to determine recommendation"),
            "confidence": result.get("confidence", 0.5),
        }
