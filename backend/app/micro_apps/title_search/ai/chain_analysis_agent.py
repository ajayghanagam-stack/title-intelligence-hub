"""Combined chain-of-title + anomaly detection agent.

Replaces separate ChainBuilderAgent + AnomalyDetectorAgent with a single
`call_json_structured()` call (native JSON schema — faster than tool-use).
"""

import uuid

from app.ai.base_service import BaseAIService

# --- Prompt version: chain_analysis_v1 ---
# Bump version comment when changing prompt text (hash auto-updates via version_tracker).
CHAIN_ANALYSIS_SYSTEM_PROMPT = """You are a chain-of-title analyst and anomaly detector. Given a list of parsed
documents, perform TWO tasks:

## TASK 1 — Build Chain of Title

Assemble documents into a chronological chain of title. For each link:
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

## TASK 2 — Detect Anomalies

Identify potential risks and anomalies in the chain and documents.

Flag types:
- chain_gap: Missing link in chain of title
- name_mismatch: Names don't match between consecutive links
- unreleased_mortgage: Mortgage with no corresponding satisfaction
- unsatisfied_lien: Lien with no release
- judgment_match: Judgment against a party in the chain
- easement_conflict: Easement that may affect use
- missing_source: Expected source not found
- low_confidence: AI parsing confidence below threshold

Severity levels: critical, high, medium, low

For each flag provide:
- flag_type, severity, title, description
- document_id (if applicable)
- chain_link_id (if applicable)

## OUTPUT

Return a JSON object with chain_links, anomalies (list of flags), and chain_complete (boolean).
"""

CHAIN_ANALYSIS_JSON_SCHEMA = {
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
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flag_type": {
                        "type": "string",
                        "enum": [
                            "chain_gap", "name_mismatch", "unreleased_mortgage",
                            "unsatisfied_lien", "judgment_match", "easement_conflict",
                            "missing_source", "low_confidence",
                        ],
                    },
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "document_id": {"type": "string"},
                    "chain_link_id": {"type": "string"},
                },
                "required": ["flag_type", "severity", "title", "description"],
            },
        },
        "chain_complete": {"type": "boolean"},
    },
    "required": ["chain_links", "anomalies", "chain_complete"],
}


class ChainAnalysisAgent(BaseAIService):
    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        from app.micro_apps.title_search.ai._model import get_ta_claude_model
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)
        ta_model = get_ta_claude_model()
        if ta_model and self._provider == "claude":
            self.model = ta_model

    async def analyze(self, documents: list[dict]) -> dict:
        """Build chain of title and detect anomalies in a single LLM call.

        Args:
            documents: list of dicts with doc fields + "id" key

        Returns:
            {"chain_links": [...], "anomalies": [...], "chain_complete": bool}
        """
        docs_text = "\n\n".join(
            f"Document {d.get('id', 'unknown')}:\n"
            f"  Type: {d.get('doc_type', 'unknown')}\n"
            f"  Date: {d.get('recording_date', 'unknown')}\n"
            f"  Ref: {d.get('recording_ref', 'unknown')}\n"
            f"  Grantor: {d.get('grantor', {})}\n"
            f"  Grantee: {d.get('grantee', {})}\n"
            f"  Consideration: {d.get('consideration', 'N/A')}\n"
            f"  Confidence: {d.get('confidence', 'N/A')}"
            for d in documents
        )

        result = await self.call_json_structured(
            system_prompt=CHAIN_ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Documents:\n{docs_text}"}],
            json_schema=CHAIN_ANALYSIS_JSON_SCHEMA,
            max_tokens=8192,
            temperature=0.0,  # Deterministic: pinned for reproducibility
        )
        return result
