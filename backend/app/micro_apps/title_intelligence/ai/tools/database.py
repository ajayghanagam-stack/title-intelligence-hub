"""Database query tools for AI agents, matching V2's tools/database.ts.

Each tool function takes pack_id/org_id from the closure and returns JSON-serializable data.
"""

import uuid
import json
import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag, Review

logger = logging.getLogger(__name__)


# --- Tool definitions (Anthropic format) ---

GET_PACK_FILES_TOOL = {
    "name": "get_pack_files",
    "description": "List all files in the pack with their IDs and page counts",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

GET_PAGES_TOOL = {
    "name": "get_pages",
    "description": "List pages for a specific pack file. Returns page numbers and whether OCR text is available.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Pack file ID"},
        },
        "required": ["file_id"],
    },
}

GET_SECTIONS_TOOL = {
    "name": "get_sections",
    "description": "List all detected document sections in the pack",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

GET_EXTRACTIONS_TOOL = {
    "name": "get_extractions",
    "description": "List all extractions for the pack",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

GET_EXTRACTIONS_BY_TYPE_TOOL = {
    "name": "get_extractions_by_type",
    "description": "Get extractions filtered by type (party, property_info, requirement, exception, endorsement, legal_description)",
    "input_schema": {
        "type": "object",
        "properties": {
            "extraction_type": {"type": "string", "enum": ["party", "property_info", "requirement", "exception", "endorsement", "legal_description"]},
        },
        "required": ["extraction_type"],
    },
}

CREATE_SECTIONS_TOOL = {
    "name": "create_sections",
    "description": "Create document sections. Each section has section_type, start_page, end_page, and confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_type": {"type": "string", "enum": ["schedule_a", "schedule_b", "schedule_c", "endorsements", "legal_description"]},
                        "start_page": {"type": "integer"},
                        "end_page": {"type": "integer"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["section_type", "start_page", "end_page", "confidence"],
                },
            },
        },
        "required": ["sections"],
    },
}

CREATE_EXTRACTIONS_TOOL = {
    "name": "create_extractions",
    "description": "Create extracted data items. Each extraction has extraction_type, label, value, evidence_refs, and confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "extractions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "extraction_type": {"type": "string", "enum": ["party", "property_info", "requirement", "exception", "endorsement", "legal_description"]},
                        "label": {"type": "string"},
                        "value": {"type": "object"},
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
                        "confidence": {"type": "number"},
                    },
                    "required": ["extraction_type", "label", "value", "evidence_refs", "confidence"],
                },
            },
        },
        "required": ["extractions"],
    },
}

DELETE_SECTIONS_TOOL = {
    "name": "delete_sections",
    "description": "Delete all sections for idempotent retry",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

DELETE_EXTRACTIONS_TOOL = {
    "name": "delete_extractions",
    "description": "Delete all extractions for idempotent retry",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

GET_FLAGS_TOOL = {
    "name": "get_flags",
    "description": "Get risk flags, optionally filtered by severity and/or status",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
            "status": {"type": "string", "enum": ["open", "approved", "rejected", "escalated"]},
        },
    },
}

CREATE_FLAGS_TOOL = {
    "name": "create_flags",
    "description": "Create risk flags. Each flag has flag_type, severity, title, description, ai_explanation, and evidence_refs.",
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

GET_REVIEWS_BY_FLAG_TOOL = {
    "name": "get_reviews_by_flag",
    "description": "Get reviews for a specific flag",
    "input_schema": {
        "type": "object",
        "properties": {
            "flag_id": {"type": "string"},
        },
        "required": ["flag_id"],
    },
}


def create_db_tool_handlers(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> dict:
    """Create tool handler functions bound to a specific db session, org, and pack."""

    async def get_pack_files(**kwargs):
        result = await db.execute(
            select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
        )
        files = result.scalars().all()
        return [{"id": str(f.id), "filename": f.filename, "page_count": f.page_count} for f in files]

    async def get_pages(file_id: str, **kwargs):
        result = await db.execute(
            select(Page).where(
                Page.file_id == uuid.UUID(file_id), Page.pack_id == pack_id, Page.org_id == org_id
            ).order_by(Page.page_number)
        )
        pages = result.scalars().all()
        return [{"page_number": p.page_number, "has_text": bool(p.ocr_text)} for p in pages]

    async def get_sections(**kwargs):
        result = await db.execute(
            select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id)
        )
        sections = result.scalars().all()
        return [
            {"id": str(s.id), "section_type": s.section_type,
             "start_page": s.start_page, "end_page": s.end_page,
             "confidence": s.confidence}
            for s in sections
        ]

    async def get_extractions(**kwargs):
        result = await db.execute(
            select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
        )
        exts = result.scalars().all()
        return [
            {"id": str(e.id), "extraction_type": e.extraction_type,
             "label": e.label, "value": e.value,
             "evidence_refs": e.evidence_refs, "confidence": e.confidence}
            for e in exts
        ]

    async def get_extractions_by_type(extraction_type: str, **kwargs):
        result = await db.execute(
            select(Extraction).where(
                Extraction.pack_id == pack_id, Extraction.org_id == org_id,
                Extraction.extraction_type == extraction_type,
            )
        )
        exts = result.scalars().all()
        return [
            {"id": str(e.id), "extraction_type": e.extraction_type,
             "label": e.label, "value": e.value,
             "evidence_refs": e.evidence_refs, "confidence": e.confidence}
            for e in exts
        ]

    async def create_sections(sections: list, **kwargs):
        created = []
        for s in sections:
            section = Section(
                pack_id=pack_id, org_id=org_id,
                section_type=s["section_type"],
                start_page=s["start_page"],
                end_page=s["end_page"],
                confidence=s.get("confidence", 0.5),
            )
            db.add(section)
            await db.flush()
            created.append(str(section.id))
        return {"created": len(created), "ids": created}

    async def create_extractions(extractions: list, **kwargs):
        created = []
        for e in extractions:
            extraction = Extraction(
                pack_id=pack_id, org_id=org_id,
                extraction_type=e["extraction_type"],
                label=e["label"],
                value=e.get("value", {}),
                evidence_refs=e.get("evidence_refs", []),
                confidence=e.get("confidence", 0.5),
            )
            db.add(extraction)
            await db.flush()
            created.append(str(extraction.id))
        return {"created": len(created), "ids": created}

    async def delete_sections_handler(**kwargs):
        await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
        return {"deleted": True}

    async def delete_extractions_handler(**kwargs):
        await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
        return {"deleted": True}

    async def get_flags(severity: str | None = None, status: str | None = None, **kwargs):
        query = select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
        if severity:
            query = query.where(Flag.severity == severity)
        if status:
            query = query.where(Flag.status == status)
        result = await db.execute(query)
        flags = result.scalars().all()
        return [
            {"id": str(f.id), "flag_type": f.flag_type, "severity": f.severity,
             "title": f.title, "description": f.description,
             "ai_explanation": f.ai_explanation, "evidence_refs": f.evidence_refs,
             "status": f.status}
            for f in flags
        ]

    async def create_flags_handler(flags: list, **kwargs):
        created = []
        for f in flags:
            flag = Flag(
                pack_id=pack_id, org_id=org_id,
                flag_type=f["flag_type"],
                severity=f["severity"],
                title=f["title"],
                description=f["description"],
                ai_explanation=f["ai_explanation"],
                evidence_refs=f.get("evidence_refs", []),
            )
            db.add(flag)
            await db.flush()
            created.append(str(flag.id))
        return {"created": len(created), "ids": created}

    async def get_reviews_by_flag(flag_id: str, **kwargs):
        result = await db.execute(
            select(Review).where(Review.flag_id == uuid.UUID(flag_id), Review.org_id == org_id)
        )
        reviews = result.scalars().all()
        return [
            {"id": str(r.id), "decision": r.decision,
             "reason_code": r.reason_code, "notes": r.notes}
            for r in reviews
        ]

    return {
        "get_pack_files": get_pack_files,
        "get_pages": get_pages,
        "get_sections": get_sections,
        "get_extractions": get_extractions,
        "get_extractions_by_type": get_extractions_by_type,
        "create_sections": create_sections,
        "create_extractions": create_extractions,
        "delete_sections": delete_sections_handler,
        "delete_extractions": delete_extractions_handler,
        "get_flags": get_flags,
        "create_flags": create_flags_handler,
        "get_reviews_by_flag": get_reviews_by_flag,
    }
