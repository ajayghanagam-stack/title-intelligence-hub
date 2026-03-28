"""Extraction config registry for specialized document-type routing.

Each document type gets a focused system prompt and JSON schema that only
includes the relevant extraction types and flag types. This reduces prompt
size (200-500 tokens vs 1300) and output tokens, improving LLM throughput.

The generic config is the full examiner prompt (fallback for unknown types).
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Shared sub-schemas (reused across configs)
_EVIDENCE_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer"},
        "text_snippet": {"type": "string", "maxLength": 200},
    },
    "required": ["page_number", "text_snippet"],
}

_PAGE_TRANSCRIPTIONS_SCHEMA = {
    "type": "array",
    "description": "Full text transcription of each page.",
    "items": {
        "type": "object",
        "properties": {
            "page_number": {"type": "integer"},
            "text": {"type": "string"},
        },
        "required": ["page_number", "text"],
    },
}


def _sections_schema(allowed_types: list[str] | None = None) -> dict:
    """Build sections schema, optionally restricted to specific types."""
    all_types = [
        "schedule_a", "schedule_b1", "schedule_b2",
        "schedule_c", "legal_description", "endorsements",
    ]
    enum = allowed_types or all_types
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "section_type": {"type": "string", "enum": enum},
                "start_page": {"type": "integer"},
                "end_page": {"type": "integer"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["section_type", "start_page", "end_page"],
        },
    }


# Typed extraction value schemas (matching title_examiner_agent.py definitions)
_TYPED_VALUE_PROPERTIES = {
    "party": {
        "name": {"type": "string"},
        "role": {"type": "string"},
        "entity_type": {"type": "string"},
        "marital_status": {"type": "string"},
        "deceased": {"type": "boolean"},
        "date_of_death": {"type": "string"},
    },
    "property": {
        "address": {"type": "string"},
        "apn": {"type": "string"},
        "county": {"type": "string"},
        "state": {"type": "string"},
        "legal_description": {"type": "string"},
        "lot": {"type": "string"},
        "block": {"type": "string"},
        "subdivision": {"type": "string"},
    },
    "requirement": {
        "number": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "risk_level": {"type": "string"},
        "is_standard_boilerplate": {"type": "boolean"},
    },
    "exception": {
        "number": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "risk_level": {"type": "string"},
        "recording_reference": {"type": "string"},
    },
    "endorsement": {
        "number": {"type": "string"},
        "endorsement_type": {"type": "string"},
        "coverage_amount": {"type": "string"},
    },
    "policy_info": {
        "field_name": {"type": "string"},
        "field_value": {"type": "string"},
    },
    "compliance": {
        "item": {"type": "string"},
        "status": {"type": "string"},
        "details": {"type": "string"},
    },
    "chain_of_title": {
        "document_type": {"type": "string"},
        "grantor": {"type": "string"},
        "grantee": {"type": "string"},
        "recording_date": {"type": "string"},
        "recording_reference": {"type": "string"},
        "consideration": {"type": "string"},
    },
}

# extraction_type → typed array key in JSON schema
_TYPE_TO_ARRAY_KEY = {
    "party": "parties",
    "property": "properties",
    "requirement": "requirements",
    "exception": "exceptions",
    "endorsement": "endorsements",
    "policy_info": "policy_info_items",
    "compliance": "compliance_items",
    "chain_of_title": "chain_of_title_items",
}


def _typed_extraction_array(extraction_type: str) -> dict:
    """Build a typed extraction array schema for a specific extraction type."""
    value_props = _TYPED_VALUE_PROPERTIES[extraction_type]
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "value": {
                    "type": "object",
                    "properties": value_props,
                    "required": list(value_props.keys()),
                },
                "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["label", "value"],
        },
    }


def _typed_extraction_schemas(allowed_types: list[str] | None = None) -> dict[str, dict]:
    """Build typed extraction array schemas, optionally restricted to specific types.

    Returns a dict of {array_key: schema} to spread into the top-level properties.
    """
    all_types = [
        "party", "property", "requirement", "exception",
        "endorsement", "policy_info", "compliance", "chain_of_title",
    ]
    types_to_include = allowed_types or all_types
    result = {}
    for ext_type in types_to_include:
        array_key = _TYPE_TO_ARRAY_KEY[ext_type]
        result[array_key] = _typed_extraction_array(ext_type)
    return result


def _flags_schema(allowed_types: list[str] | None = None) -> dict:
    """Build flags schema, optionally restricted to specific types."""
    all_types = [
        "missing_endorsement", "unacceptable_exception",
        "unresolved_lien", "unreleased_mortgage",
        "cross_section_mismatch", "requirement_missing_proof",
        "name_discrepancy", "marital_status_issue",
        "incomplete_document", "regulatory_compliance",
        "chain_of_title_gap", "document_defect",
        "mineral_rights", "trust_issue",
        "estate_issue", "vesting_issue", "tax_issue",
    ]
    enum = allowed_types or all_types
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "flag_type": {"type": "string", "enum": enum},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "ai_explanation": {"type": "string"},
                "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
            },
            "required": ["flag_type", "severity", "title", "description", "ai_explanation", "evidence_refs"],
        },
    }


def _build_json_schema(
    sections_types: list[str] | None = None,
    extraction_types: list[str] | None = None,
    flag_types: list[str] | None = None,
) -> dict:
    """Build a complete examination JSON schema with optional type restrictions.

    Uses typed extraction arrays (parties[], properties[], etc.) instead of a
    single polymorphic extractions[] array to reduce output token bloat.
    """
    typed_schemas = _typed_extraction_schemas(extraction_types)
    return {
        "type": "object",
        "properties": {
            "page_transcriptions": _PAGE_TRANSCRIPTIONS_SCHEMA,
            "sections": _sections_schema(sections_types),
            **typed_schemas,
            "flags": _flags_schema(flag_types),
        },
        "required": [
            "page_transcriptions", "sections",
            *typed_schemas.keys(),
            "flags",
        ],
    }


@dataclass(frozen=True)
class ExtractionConfig:
    """Configuration for a document-type-specific extractor."""

    doc_type: str
    system_prompt: str
    json_schema: dict = field(repr=False)


# --- Focused system prompts per document type ---

_COMMITMENT_PROMPT = """\
You are an expert title examiner analyzing TITLE COMMITMENT pages (T-7 schedules). \
Transcribe all text, identify schedule sections, extract structured data, and flag issues.

Focus on: Schedule A (effective date, parties, property, policy amounts), \
Schedule B-I (requirements), Schedule B-II (exceptions), Schedule C (conditions), \
legal descriptions, and policy information.

Extract: party (all named parties with roles), property (address, APN, legal), \
requirement (each B-I item), exception (each B-II item), policy_info \
(commitment number, effective date, amounts, insured, underwriter), compliance items.

Flag: cross_section_mismatch, requirement_missing_proof, missing_endorsement, \
name_discrepancy, marital_status_issue, incomplete_document, regulatory_compliance.\
"""

_DEED_PROMPT = """\
You are an expert title examiner analyzing a DEED (warranty, quitclaim, or special warranty). \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: grantor, grantee, legal description, consideration, recording info, \
stamps, notary blocks, and chain of title continuity.

Extract: party (grantor/grantee with roles), property (legal description, APN), \
chain_of_title (recording date, instrument number, type, amount).

Flag: name_discrepancy, chain_of_title_gap, document_defect, incomplete_document, \
marital_status_issue.\
"""

_MORTGAGE_PROMPT = """\
You are an expert title examiner analyzing a MORTGAGE or DEED OF TRUST. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: borrower/trustor, lender/beneficiary, loan amount, property, \
recording info, maturity date, and encumbrance details.

Extract: party (borrower, lender with roles), property (legal description), \
chain_of_title (recording info, instrument number, type, amount).

Flag: unreleased_mortgage, name_discrepancy, document_defect, incomplete_document, \
marital_status_issue.\
"""

_LIEN_PROMPT = """\
You are an expert title examiner analyzing a LIEN, JUDGMENT, or ASSESSMENT document. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: lienholder, debtor/property owner, lien amount, property affected, \
recording info, lien type, and satisfaction status.

Extract: party (lienholder, debtor with roles), property (address, legal), \
chain_of_title (recording info), compliance (regulatory items).

Flag: unresolved_lien, name_discrepancy, document_defect, incomplete_document, \
regulatory_compliance.\
"""

_RELEASE_PROMPT = """\
You are an expert title examiner analyzing a RELEASE, SATISFACTION, or RECONVEYANCE. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: releasing party, released instrument reference (book/page or instrument number), \
recording info, and whether the release properly matches its encumbrance.

Extract: party (releasing party, released party with roles), \
chain_of_title (released instrument recording info, release recording info).

Flag: unreleased_mortgage (if release appears incomplete), document_defect, \
incomplete_document, name_discrepancy.\
"""

_EASEMENT_PROMPT = """\
You are an expert title examiner analyzing an EASEMENT, RESTRICTION, or CC&R document. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: parties (grantor of easement, beneficiary), easement type, \
property/area affected, recording info, and any restrictions on use.

Extract: party (grantor, beneficiary with roles), property (affected area, legal), \
chain_of_title (recording info).

Flag: unacceptable_exception, document_defect, incomplete_document, name_discrepancy.\
"""

_PLAT_PROMPT = """\
You are an expert title examiner analyzing a PLAT MAP, SURVEY, or LEGAL DESCRIPTION document. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: subdivision name, lot/block numbers, metes and bounds, recording info, \
surveyor certification, and any easements or dedications shown on the plat.

Extract: property (subdivision, lot/block, legal description, plat reference), \
party (surveyor, subdivider if named), chain_of_title (recording info).

Flag: document_defect, incomplete_document.\
"""

_ENDORSEMENT_PROMPT = """\
You are an expert title examiner analyzing TITLE INSURANCE ENDORSEMENTS. \
Transcribe all text, identify sections, extract structured data, and flag issues.

Focus on: endorsement number/form, type of coverage, coverage amount, \
effective date, and any conditions or limitations.

Extract: endorsement (number, type, coverage amount, conditions).

Flag: missing_endorsement, incomplete_document.\
"""


# --- Registry ---

# Build configs with focused schemas per doc type
_CONFIGS: dict[str, ExtractionConfig] = {
    "commitment": ExtractionConfig(
        doc_type="commitment",
        system_prompt=_COMMITMENT_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["schedule_a", "schedule_b1", "schedule_b2", "schedule_c", "legal_description"],
            extraction_types=["party", "property", "requirement", "exception", "policy_info", "compliance"],
            flag_types=[
                "cross_section_mismatch", "requirement_missing_proof", "missing_endorsement",
                "name_discrepancy", "marital_status_issue", "incomplete_document", "regulatory_compliance",
            ],
        ),
    ),
    "deed": ExtractionConfig(
        doc_type="deed",
        system_prompt=_DEED_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["legal_description"],
            extraction_types=["party", "property", "chain_of_title"],
            flag_types=[
                "name_discrepancy", "chain_of_title_gap", "document_defect",
                "incomplete_document", "marital_status_issue",
            ],
        ),
    ),
    "mortgage": ExtractionConfig(
        doc_type="mortgage",
        system_prompt=_MORTGAGE_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["legal_description"],
            extraction_types=["party", "property", "chain_of_title"],
            flag_types=[
                "unreleased_mortgage", "name_discrepancy", "document_defect",
                "incomplete_document", "marital_status_issue",
            ],
        ),
    ),
    "lien": ExtractionConfig(
        doc_type="lien",
        system_prompt=_LIEN_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["legal_description"],
            extraction_types=["party", "property", "chain_of_title", "compliance"],
            flag_types=[
                "unresolved_lien", "name_discrepancy", "document_defect",
                "incomplete_document", "regulatory_compliance",
            ],
        ),
    ),
    "release": ExtractionConfig(
        doc_type="release",
        system_prompt=_RELEASE_PROMPT,
        json_schema=_build_json_schema(
            sections_types=None,  # releases don't have standard sections
            extraction_types=["party", "chain_of_title"],
            flag_types=[
                "unreleased_mortgage", "document_defect",
                "incomplete_document", "name_discrepancy",
            ],
        ),
    ),
    "easement": ExtractionConfig(
        doc_type="easement",
        system_prompt=_EASEMENT_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["legal_description"],
            extraction_types=["party", "property", "chain_of_title"],
            flag_types=[
                "unacceptable_exception", "document_defect",
                "incomplete_document", "name_discrepancy",
            ],
        ),
    ),
    "plat": ExtractionConfig(
        doc_type="plat",
        system_prompt=_PLAT_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["legal_description"],
            extraction_types=["property", "party", "chain_of_title"],
            flag_types=["document_defect", "incomplete_document"],
        ),
    ),
    "endorsement": ExtractionConfig(
        doc_type="endorsement",
        system_prompt=_ENDORSEMENT_PROMPT,
        json_schema=_build_json_schema(
            sections_types=["endorsements"],
            extraction_types=["endorsement"],
            flag_types=["missing_endorsement", "incomplete_document"],
        ),
    ),
}

# Generic config uses the full examiner prompt (imported lazily to avoid circular imports)
_generic_config: ExtractionConfig | None = None


def _get_generic_config() -> ExtractionConfig:
    """Lazily build the generic config from the full examiner prompt/schema."""
    global _generic_config
    if _generic_config is not None:
        return _generic_config

    from app.micro_apps.title_intelligence.ai.title_examiner_agent import (
        SYSTEM_PROMPT,
        EXAMINATION_JSON_SCHEMA,
    )
    _generic_config = ExtractionConfig(
        doc_type="generic",
        system_prompt=SYSTEM_PROMPT,
        json_schema=EXAMINATION_JSON_SCHEMA,
    )
    return _generic_config


def get_extraction_config(doc_type: str) -> ExtractionConfig:
    """Get the extraction config for a document type.

    Returns the specialized config if available, otherwise the generic fallback.

    Args:
        doc_type: Document type string (e.g., "deed", "mortgage", "commitment").

    Returns:
        ExtractionConfig with focused prompt and schema.
    """
    config = _CONFIGS.get(doc_type)
    if config is not None:
        return config
    return _get_generic_config()


def compute_registry_hash() -> str:
    """Compute a deterministic hash of all extraction configs.

    Used for version tracking — any change to prompts or schemas
    produces a different hash, invalidating the pipeline cache.
    """
    parts = []
    for doc_type in sorted(_CONFIGS.keys()):
        cfg = _CONFIGS[doc_type]
        parts.append(cfg.system_prompt)
        parts.append(json.dumps(cfg.json_schema, sort_keys=True))
    combined = "".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def list_doc_types() -> list[str]:
    """Return all supported specialized doc types (excluding generic)."""
    return sorted(_CONFIGS.keys())
