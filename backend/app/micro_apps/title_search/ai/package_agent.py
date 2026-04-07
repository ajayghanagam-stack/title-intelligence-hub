import uuid

from app.ai.base_service import BaseAIService

PACKAGE_SYSTEM_PROMPT = """You are a title abstract package writer. Generate a professional narrative summary
for a title search abstract package.

Include sections:
1. Property Summary — address, parcel, legal description
2. Search Scope — years covered, source types searched
3. Chain of Title — chronological summary of ownership transfers
4. Encumbrances — mortgages, liens, easements found
5. Flags & Issues — any unresolved items requiring attention
6. Conclusion — overall assessment of title condition

Write in professional, concise legal style.
"""


class PackageAgent(BaseAIService):
    def __init__(self, org_id: uuid.UUID):
        from app.config import get_settings
        settings = get_settings()
        provider_override = settings.TA_AI_PROVIDER or None
        super().__init__(org_id, provider_override=provider_override)

    async def generate_narrative(
        self,
        property_summary: dict,
        documents: list[dict],
        chain_links: list[dict],
        flags: list[dict],
        search_scope: str,
        years_covered: int,
    ) -> str:
        """Generate a narrative summary for the abstract package."""
        content = (
            f"Property: {property_summary}\n"
            f"Search Scope: {search_scope}, {years_covered} years\n"
            f"Documents ({len(documents)}):\n"
        )
        for d in documents:
            content += f"  - {d.get('doc_type', 'unknown')}: {d.get('recording_ref', 'N/A')} ({d.get('recording_date', 'N/A')})\n"

        content += f"\nChain of Title ({len(chain_links)} links):\n"
        for cl in chain_links:
            content += (
                f"  {cl.get('position', '?')}. {cl.get('from_party', {})} → "
                f"{cl.get('to_party', {})} ({cl.get('effective_date', 'N/A')})\n"
            )

        if flags:
            content += f"\nFlags ({len(flags)}):\n"
            for f in flags:
                content += f"  - [{f.get('severity', '?')}] {f.get('title', '')}: {f.get('description', '')}\n"

        return await self.call_haiku(
            system_prompt=PACKAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
        )
