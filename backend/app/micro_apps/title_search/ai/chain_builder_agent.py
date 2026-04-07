import uuid

from app.ai.base_service import BaseAIService

# --- Prompt version: chain_v1 ---
# Bump version comment when changing prompt text (hash auto-updates via version_tracker).
CHAIN_SYSTEM_PROMPT = """You are a chain-of-title analyst. Given a list of parsed documents, assemble them into
a chronological chain of title.

For each link in the chain, identify:
- position: sequential order (1-based)
- link_type: conveyance (ownership transfer), encumbrance (mortgage/lien/easement), release (satisfaction/release), or gap (missing link)
- document_id: the UUID of the related document
- from_party: who conveyed (names list)
- to_party: who received (names list)
- effective_date: YYYY-MM-DD
- is_gap: true if this is a gap in the chain
- gap_description: description of the gap if applicable

Check for:
- Chronological ordering by recording_date
- Name continuity (grantee of one link should match grantor of next)
- Missing links between owners
"""

CHAIN_TOOL = {
    "name": "submit_chain",
    "description": "Submit the assembled chain of title",
    "input_schema": {
        "type": "object",
        "properties": {
            "chain_links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "integer"},
                        "link_type": {"type": "string", "enum": ["conveyance", "encumbrance", "release", "gap"]},
                        "document_id": {"type": "string"},
                        "from_party": {
                            "type": "object",
                            "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                        },
                        "to_party": {
                            "type": "object",
                            "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                        },
                        "effective_date": {"type": "string"},
                        "is_gap": {"type": "boolean"},
                        "gap_description": {"type": "string"},
                    },
                    "required": ["position", "link_type"],
                },
            },
            "chain_complete": {"type": "boolean"},
        },
        "required": ["chain_links", "chain_complete"],
    },
}


class ChainBuilderAgent(BaseAIService):
    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)

    async def build(self, documents: list[dict]) -> dict:
        """Build chain of title from parsed documents.

        Args:
            documents: list of dicts with doc fields + "id" key

        Returns:
            {"chain_links": [...], "chain_complete": bool}
        """
        docs_text = "\n\n".join(
            f"Document {d.get('id', 'unknown')}:\n"
            f"  Type: {d.get('doc_type', 'unknown')}\n"
            f"  Date: {d.get('recording_date', 'unknown')}\n"
            f"  Ref: {d.get('recording_ref', 'unknown')}\n"
            f"  Grantor: {d.get('grantor', {})}\n"
            f"  Grantee: {d.get('grantee', {})}\n"
            f"  Consideration: {d.get('consideration', 'N/A')}"
            for d in documents
        )

        result = await self.call_haiku_structured(
            system_prompt=CHAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Documents:\n{docs_text}"}],
            tools=[CHAIN_TOOL],
            max_tokens=4096,
            temperature=0.0,  # Deterministic: pinned for reproducibility
        )
        return result
