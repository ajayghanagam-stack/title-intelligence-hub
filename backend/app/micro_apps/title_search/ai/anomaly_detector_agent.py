import uuid

from app.ai.base_service import BaseAIService

# --- Prompt version: anomaly_v1 ---
# Bump version comment when changing prompt text (hash auto-updates via version_tracker).
ANOMALY_SYSTEM_PROMPT = """You are a title anomaly detector. Given a chain of title and parsed documents,
identify potential risks and anomalies.

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
"""

ANOMALY_TOOL = {
    "name": "submit_flags",
    "description": "Submit detected anomalies and risk flags",
    "input_schema": {
        "type": "object",
        "properties": {
            "flags": {
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
        },
        "required": ["flags"],
    },
}


class AnomalyDetectorAgent(BaseAIService):
    async def detect(self, chain_links: list[dict], documents: list[dict]) -> list[dict]:
        """Detect anomalies in chain of title and documents.

        Returns:
            List of flag dicts with flag_type, severity, title, description, etc.
        """
        chain_text = "\n".join(
            f"Link {cl.get('position', '?')}: {cl.get('link_type', '?')} | "
            f"From: {cl.get('from_party', {})} → To: {cl.get('to_party', {})} | "
            f"Date: {cl.get('effective_date', '?')} | Gap: {cl.get('is_gap', False)}"
            for cl in chain_links
        )

        docs_text = "\n".join(
            f"Doc {d.get('id', '?')}: {d.get('doc_type', '?')} | "
            f"Date: {d.get('recording_date', '?')} | "
            f"Confidence: {d.get('confidence', '?')}"
            for d in documents
        )

        content = f"Chain of Title:\n{chain_text}\n\nDocuments:\n{docs_text}"

        result = await self.call_haiku_structured(
            system_prompt=ANOMALY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[ANOMALY_TOOL],
            max_tokens=4096,
            temperature=0.0,  # Deterministic: pinned for reproducibility
        )
        return result.get("flags", [])
