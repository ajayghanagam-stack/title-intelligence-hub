import uuid

from app.ai.base_service import BaseAIService

# --- Prompt version: parser_v1 ---
# Bump version comment when changing prompt text (hash auto-updates via version_tracker).
PARSER_SYSTEM_PROMPT = """You are a title document parser. Given raw document content, extract structured fields.

Return a tool call with:
- doc_type: one of deed, mortgage, lien, judgment, easement, hoa, satisfaction, release, assignment, other
- recording_date: YYYY-MM-DD format if found
- recording_ref: recording reference number
- legal_description: property legal description
- consideration: dollar amount as number (no $ sign)
- grantor: object with "names" (list of strings) and "entity_type" (individual/corporation/trust/government)
- grantee: object with "names" (list of strings) and "entity_type"
- summary: brief summary of the document
- confidence: 0.0 to 1.0 confidence score
"""

PARSER_TOOL = {
    "name": "submit_parsed_document",
    "description": "Submit the parsed document fields",
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_type": {
                "type": "string",
                "enum": ["deed", "mortgage", "lien", "judgment", "easement",
                         "hoa", "satisfaction", "release", "assignment", "other"],
            },
            "recording_date": {"type": "string", "description": "YYYY-MM-DD"},
            "recording_ref": {"type": "string"},
            "legal_description": {"type": "string"},
            "consideration": {"type": "number"},
            "grantor": {
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                    "entity_type": {"type": "string"},
                },
            },
            "grantee": {
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                    "entity_type": {"type": "string"},
                },
            },
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["doc_type", "confidence"],
    },
}


class DocumentParserAgent(BaseAIService):
    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        from app.micro_apps.title_search.ai._model import get_ta_claude_model
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)
        ta_model = get_ta_claude_model()
        if ta_model and self._provider == "claude":
            self.model = ta_model

    async def parse(self, raw_content: str) -> dict:
        """Parse raw document content into structured fields."""
        result = await self.call_haiku_structured(
            system_prompt=PARSER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_content}],
            tools=[PARSER_TOOL],
            max_tokens=2048,
            temperature=0.0,  # Deterministic: pinned for reproducibility
        )
        # Set needs_review if confidence is low
        confidence = result.get("confidence", 0.0)
        result["needs_review"] = confidence < 0.70
        return result
