"""Report agent with prefetch pattern + upload tool matching V2.

All data is prefetched before the LLM call. Single upload_report tool for saving.
Supports text, markdown, PDF, and JSON output formats.
"""

import uuid
import logging
from typing import Any

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)

AUDIENCE_PROMPTS = {
    "attorney": "Write a detailed attorney memo suitable for legal review. Include all relevant legal details, exceptions, requirements, and risk analysis.",
    "lender": "Write a concise lender summary focusing on title clearance status, outstanding requirements, and closing readiness.",
    "buyer": "Write a plain-language overview for the buyer. Explain any issues in simple terms and summarize overall title status.",
    "underwriter": "Write a technical underwriting report. Include detailed risk analysis, flag assessment, and readiness scoring breakdown.",
}


class ReportAgent(BaseAIService):
    """Generate audience-specific reports with prefetch pattern."""

    SYSTEM_PROMPT = """You are a title insurance report writer.
Generate professional, accurate reports based on the provided title analysis data.
Include relevant details from extractions, flag analysis, and readiness assessment.
Maintain appropriate tone and detail level for the target audience.

Structure the report with clear sections:
1. Executive Summary
2. Property Information
3. Parties
4. Requirements Status
5. Exceptions Analysis
6. Risk Flags
7. Readiness Assessment
8. Recommendations"""

    async def generate(
        self,
        pack_name: str,
        audience: str,
        format: str,
        extractions: list,
        flags: list,
        readiness_score: int,
        readiness_summary: str | None,
    ) -> str:
        """Generate an audience-specific report.

        All data is prefetched — single LLM call with full context.
        """
        audience_instruction = AUDIENCE_PROMPTS.get(audience, AUDIENCE_PROMPTS["buyer"])

        extraction_text = "\n".join(
            f"- [{e.extraction_type}] {e.label}: {e.value}" for e in extractions
        ) if extractions else "No extractions available."

        flag_text = "\n".join(
            f"- [{f.severity.upper()}] {f.title}: {f.description} (Status: {f.status})"
            for f in flags
        ) if flags else "No flags identified."

        context = (
            f"Title Pack: {pack_name}\n"
            f"Readiness Score: {readiness_score}/100\n"
            f"Summary: {readiness_summary or 'Not yet generated'}\n\n"
            f"Extractions:\n{extraction_text}\n\n"
            f"Risk Flags:\n{flag_text}"
        )

        format_instruction = ""
        if format in ("markdown", "pdf"):
            format_instruction = "\nFormat the report using Markdown with headers (# ##), bullet points, and tables where appropriate."
        elif format == "json":
            format_instruction = (
                "\nReturn the report as a JSON object with these keys: "
                "executive_summary, property_info, parties, requirements, exceptions, "
                "risk_flags, readiness, recommendations. Each value should be a string or array."
            )

        messages = [{
            "role": "user",
            "content": f"{audience_instruction}{format_instruction}\n\nTitle Analysis Data:\n{context}",
        }]

        return await self.call_haiku(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            max_tokens=4096,
        )

    async def generate_summary(
        self,
        pack_name: str,
        extractions: list,
        flags: list,
        readiness_score: int,
    ) -> str:
        """Generate a concise 2-3 sentence executive summary for the readiness dashboard."""
        open_flags = [f for f in flags if f.status == "open"]
        critical_count = sum(1 for f in open_flags if f.severity == "critical")
        high_count = sum(1 for f in open_flags if f.severity == "high")

        extraction_text = "\n".join(
            f"- [{e.extraction_type}] {e.label}: {e.value}" for e in extractions
        ) if extractions else "No extractions available."

        flag_text = "\n".join(
            f"- [{f.severity.upper()}] {f.title} (Status: {f.status})"
            for f in flags
        ) if flags else "No flags identified."

        messages = [{
            "role": "user",
            "content": (
                f"Title Pack: {pack_name}\n"
                f"Readiness Score: {readiness_score}/100\n"
                f"Open Flags: {len(open_flags)} ({critical_count} critical, {high_count} high)\n\n"
                f"Extractions:\n{extraction_text}\n\n"
                f"Risk Flags:\n{flag_text}\n\n"
                "Write a concise executive summary of the title commitment's closing readiness. "
                "List ALL critical and high severity issues specifically. "
                "Be specific about what needs attention. Do not use headers or bullet points. "
                "Write in paragraph form, 3-5 sentences."
            ),
        }]

        return await self.call_haiku(
            system_prompt=(
                "You are a title insurance analyst writing a dashboard summary. "
                "Be concise, specific, and professional. Write 3-5 sentences covering all major issues. "
                "Focus on actionable insights — what is blocking closing or what makes the title ready."
            ),
            messages=messages,
            max_tokens=1024,
        )

    async def generate_structured(
        self,
        pack_name: str,
        audience: str,
        extractions: list,
        flags: list,
        readiness_score: int,
        readiness_summary: str | None,
    ) -> dict[str, Any]:
        """Generate a structured report as JSON dict.

        Returns: dict with report sections as keys.
        """
        audience_instruction = AUDIENCE_PROMPTS.get(audience, AUDIENCE_PROMPTS["buyer"])

        extraction_text = "\n".join(
            f"- [{e.extraction_type}] {e.label}: {e.value}" for e in extractions
        ) if extractions else "No extractions available."

        flag_text = "\n".join(
            f"- [{f.severity.upper()}] {f.title}: {f.description} (Status: {f.status})"
            for f in flags
        ) if flags else "No flags identified."

        context = (
            f"Title Pack: {pack_name}\n"
            f"Readiness Score: {readiness_score}/100\n"
            f"Summary: {readiness_summary or 'Not yet generated'}\n\n"
            f"Extractions:\n{extraction_text}\n\n"
            f"Risk Flags:\n{flag_text}"
        )

        tools = [{
            "name": "structured_report",
            "description": "Return the structured report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "executive_summary": {"type": "string"},
                    "property_info": {"type": "string"},
                    "parties": {"type": "string"},
                    "requirements": {"type": "string"},
                    "exceptions": {"type": "string"},
                    "risk_flags": {"type": "string"},
                    "readiness": {"type": "string"},
                    "recommendations": {"type": "string"},
                },
                "required": ["executive_summary", "property_info", "parties",
                             "requirements", "exceptions", "risk_flags",
                             "readiness", "recommendations"],
            },
        }]

        messages = [{
            "role": "user",
            "content": f"{audience_instruction}\n\nTitle Analysis Data:\n{context}",
        }]

        return await self.call_haiku_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            max_tokens=4096,
        )
