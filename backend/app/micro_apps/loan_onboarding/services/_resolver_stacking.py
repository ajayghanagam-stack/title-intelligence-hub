"""Pure-CPU layer-stacking helpers used by ``config_resolver``.

Split out so the resolver entry point in ``config_resolver.py`` stays
the readable orchestration story and these deterministic merge
functions can be unit-tested in isolation.

The stacking precedence is fixed (Global → loan_program →
investor_overlay → per-loan); each function takes pre-loaded ORM rows /
JSONB blobs and returns a tuple of frozen ``Resolved*`` records ready
to drop into ``EffectiveConfig``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema
from app.micro_apps.loan_onboarding.models.program_profile import LOProgramProfile
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.models.validation_rule_org import (
    LOValidationRuleOrg,
)
from app.micro_apps.loan_onboarding.schemas.resolved_config import (
    ResolvedDocType,
    ResolvedField,
    ResolvedRule,
    ResolvedSchema,
)


# ── Doc-type stacking ────────────────────────────────────────────────


def stack_doc_types(
    catalog: list[LODocTypeCatalog],
    loan_program: LOProgramProfile | None,
    investor_overlay: LOProgramProfile | None,
    loan_doc_cfg: LODocTypeConfig | None,
) -> tuple[ResolvedDocType, ...]:
    """Build the ordered tuple of doc types after all four layers stack.

    Tighten-only semantics: each downstream layer can promote a doc type
    from optional → required and add new entries; it cannot demote a
    required doc type to optional. (Demotions are blocked at write time
    by ``services/tighten_only.py``; the resolver trusts that.)
    """
    # Start from Global catalog — every active row is in scope, default
    # required=False unless a downstream layer flips it.
    by_key: dict[str, dict[str, Any]] = {}
    for row in catalog:
        by_key[row.key] = {
            "key": row.key,
            "name": row.name,
            "category": row.category,
            "required": False,
            "expected_min_pages": row.expected_min_pages,
            "expected_max_pages": row.expected_max_pages,
            "auto_classify_enabled": row.auto_classify_enabled,
        }

    for layer in (loan_program, investor_overlay):
        if layer is None or not layer.checklist:
            continue
        for entry in layer.checklist:
            if not isinstance(entry, dict):
                continue
            key = entry.get("doc_type_key") or entry.get("key")
            if not isinstance(key, str) or key not in by_key:
                continue
            row = by_key[key]
            if entry.get("required") is True:
                row["required"] = True
            if isinstance(entry.get("expected_min_pages"), int):
                row["expected_min_pages"] = entry["expected_min_pages"]
            if isinstance(entry.get("expected_max_pages"), int):
                row["expected_max_pages"] = entry["expected_max_pages"]

    # Per-loan layer (lowest precedence): same shape as the legacy
    # ``LODocTypeConfig.doc_types[]`` JSONB, plus a ``required`` flag.
    #
    # Defensive case-folding: legacy rows persisted before the schema-level
    # ``DocTypeSpec`` lowercasing was added may still carry UPPER_SNAKE
    # keys. Normalize at compare time so a per-loan ``URLA_1003`` still
    # elevates the catalog's ``urla_1003`` to required.
    if loan_doc_cfg and loan_doc_cfg.doc_types:
        for entry in loan_doc_cfg.doc_types:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key")
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip().lower()
            if key not in by_key:
                continue
            if entry.get("required") is True:
                by_key[key]["required"] = True

    # Stable order: required first (alphabetical), then optional
    # (alphabetical). Determinism matters for ``config_hash``.
    ordered = sorted(
        by_key.values(),
        key=lambda r: (0 if r["required"] else 1, r["key"]),
    )
    return tuple(ResolvedDocType(**r) for r in ordered)


# ── Schema stacking ──────────────────────────────────────────────────


def stack_schemas(
    catalog: list[LODocTypeCatalog],
    schema_rows: list[LOExtractionSchema],
    loan_program: LOProgramProfile | None,
    investor_overlay: LOProgramProfile | None,
) -> tuple[ResolvedSchema, ...]:
    """Build the per-doc-type field schema tuple after profile overrides.

    Per-loan field-level overrides are *not* supported at MVP (resolver
    spec §6 open question 2 — closed: doc-type-level only). Loans tweak
    which doc types are required, not the field shape.
    """
    catalog_by_id = {row.id: row for row in catalog}
    schema_by_doc_key: dict[str, dict[str, Any]] = {}

    for s in schema_rows:
        cat = catalog_by_id.get(s.doc_type_id)
        if cat is None:
            continue
        # Normalize each field row from JSONB into a mutable dict so
        # downstream layers can override individual attributes.
        fields_by_key: dict[str, dict[str, Any]] = {}
        for f in (s.fields or []):
            if not isinstance(f, dict):
                continue
            key = f.get("key")
            if not isinstance(key, str) or not key:
                continue
            fields_by_key[key] = {
                "key": key,
                "label": str(f.get("label") or key),
                "data_type": str(f.get("data_type") or "string"),
                "required": bool(f.get("required", False)),
                "min_confidence": float(f.get("min_confidence", 0.0)),
                "regex": (f.get("regex") if isinstance(f.get("regex"), str) else None),
                "alias": _coerce_alias(f.get("alias")),
            }
        schema_by_doc_key[cat.key] = {
            "version": int(s.version or 1),
            "fields_by_key": fields_by_key,
        }

    for layer in (loan_program, investor_overlay):
        if layer is None or not layer.extraction_overrides:
            continue
        for doc_key, overrides in layer.extraction_overrides.items():
            if not isinstance(overrides, dict):
                continue
            schema = schema_by_doc_key.get(doc_key)
            if schema is None:
                # Profile may add a field on a doc type with no Global
                # schema row yet — start from an empty schema.
                schema = {"version": 1, "fields_by_key": {}}
                schema_by_doc_key[doc_key] = schema
            for field_key, ovr in overrides.items():
                if not isinstance(ovr, dict):
                    continue
                existing = schema["fields_by_key"].get(field_key)
                if existing is None:
                    # Profile is adding a brand-new field. Defaults
                    # match the JSONB row shape.
                    existing = {
                        "key": field_key,
                        "label": str(ovr.get("label") or field_key),
                        "data_type": str(ovr.get("data_type") or "string"),
                        "required": False,
                        "min_confidence": 0.0,
                        "regex": None,
                        "alias": (),
                    }
                    schema["fields_by_key"][field_key] = existing
                # Tighten-only at read time: only raise required and
                # min_confidence; never lower. Write-time validators
                # already rejected the bad case but we belt-and-brace.
                if ovr.get("required") is True:
                    existing["required"] = True
                if isinstance(ovr.get("min_confidence"), (int, float)):
                    existing["min_confidence"] = max(
                        existing["min_confidence"], float(ovr["min_confidence"]),
                    )
                if isinstance(ovr.get("regex"), str):
                    existing["regex"] = ovr["regex"]
                if isinstance(ovr.get("label"), str):
                    existing["label"] = ovr["label"]

    out: list[ResolvedSchema] = []
    for doc_key in sorted(schema_by_doc_key.keys()):
        schema = schema_by_doc_key[doc_key]
        fields = tuple(
            ResolvedField(
                key=row["key"],
                label=row["label"],
                data_type=row["data_type"],
                required=row["required"],
                min_confidence=row["min_confidence"],
                regex=row["regex"],
                alias=row["alias"],
            )
            for row in sorted(
                schema["fields_by_key"].values(), key=lambda r: r["key"]
            )
        )
        out.append(ResolvedSchema(
            doc_type_key=doc_key,
            schema_version=schema["version"],
            fields=fields,
        ))
    return tuple(out)


# ── Rule stacking ────────────────────────────────────────────────────


def stack_rules(
    org_rules: list[LOValidationRuleOrg],
    loan_program: LOProgramProfile | None,
    investor_overlay: LOProgramProfile | None,
    loan_rules: list[LOValidationRule],
) -> tuple[ResolvedRule, ...]:
    """Concat rules across layers, tagging each with its source layer.

    Dedup is by ``(scope, rule)`` — if a per-loan rule re-states an org
    rule verbatim, the org rule wins (higher precedence). Profile rules
    that exactly match the org library row are silently dropped.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ResolvedRule] = []

    for r in org_rules:
        key = (r.scope, r.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append(ResolvedRule(
            scope=r.scope,
            rule=r.rule,
            condition=r.condition or "",
            preset_id=r.preset_id,
            severity=_coerce_severity(r.severity),
            layer="global",
        ))

    for layer, layer_name in (
        (loan_program, "loan_program"),
        (investor_overlay, "investor_overlay"),
    ):
        if layer is None or not layer.rule_overrides:
            continue
        for entry in layer.rule_overrides:
            if not isinstance(entry, dict):
                continue
            scope = entry.get("scope")
            rule = entry.get("rule")
            if not isinstance(scope, str) or not isinstance(rule, str):
                continue
            key = (scope, rule)
            if key in seen:
                continue
            seen.add(key)
            out.append(ResolvedRule(
                scope=scope,
                rule=rule,
                condition=str(entry.get("condition") or ""),
                preset_id=entry.get("preset_id") if isinstance(entry.get("preset_id"), str) else None,
                severity=_coerce_severity(entry.get("severity")),
                layer=layer_name,  # type: ignore[arg-type]
            ))

    for r in loan_rules:
        scope = f"doc_type:{r.doc_type}" if r.doc_type else "package"
        rule_label = r.rule_id or "custom"
        key = (scope, rule_label)
        if key in seen:
            continue
        seen.add(key)
        out.append(ResolvedRule(
            scope=scope,
            rule=rule_label,
            condition=r.description or "",
            preset_id=r.rule_id if r.rule_source == "preset" else None,
            severity="hard",  # legacy per-loan rows don't track severity
            layer="loan",
        ))

    # Stable order: layer hierarchy then (scope, rule). Determinism for
    # config_hash — if a rule is added/removed, the hash flips, but
    # otherwise re-resolves are identical bytes.
    layer_order = {"global": 0, "loan_program": 1, "investor_overlay": 2, "loan": 3}
    out.sort(key=lambda r: (layer_order[r.layer], r.scope, r.rule))
    return tuple(out)


# ── Helpers ──────────────────────────────────────────────────────────


def _coerce_alias(alias: object) -> tuple[str, ...]:
    if not alias:
        return ()
    if isinstance(alias, str):
        return (alias,)
    if isinstance(alias, (list, tuple)):
        return tuple(str(a) for a in alias if isinstance(a, str) and a)
    return ()


def _coerce_severity(s: object) -> str:
    return "soft" if str(s) == "soft" else "hard"


# ── Canonical hashing ────────────────────────────────────────────────


def compute_config_hash(
    *,
    doc_types: tuple[ResolvedDocType, ...],
    schemas: tuple[ResolvedSchema, ...],
    rules: tuple[ResolvedRule, ...],
    program_profile_id: UUID | None,
    investor_overlay_id: UUID | None,
    grounding_contract_version: str,
) -> str:
    """Deterministic SHA-256 over the canonical JSON form.

    Folded into every downstream AI cache key — when any layer of the
    resolved config changes, this hash changes, and dependent caches
    miss automatically. ``json.dumps(..., sort_keys=True)`` makes the
    serialization order-independent over dict keys; we already sort the
    tuples themselves in ``stack_*``.
    """
    payload = {
        "program_profile_id": str(program_profile_id) if program_profile_id else None,
        "investor_overlay_id": str(investor_overlay_id) if investor_overlay_id else None,
        "grounding_contract_version": grounding_contract_version,
        "doc_types": [
            {
                "key": d.key,
                "name": d.name,
                "category": d.category,
                "required": d.required,
                "expected_min_pages": d.expected_min_pages,
                "expected_max_pages": d.expected_max_pages,
                "auto_classify_enabled": d.auto_classify_enabled,
            }
            for d in doc_types
        ],
        "schemas": [
            {
                "doc_type_key": s.doc_type_key,
                "schema_version": s.schema_version,
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "data_type": f.data_type,
                        "required": f.required,
                        "min_confidence": f.min_confidence,
                        "regex": f.regex,
                        "alias": list(f.alias),
                    }
                    for f in s.fields
                ],
            }
            for s in schemas
        ],
        "rules": [
            {
                "scope": r.scope,
                "rule": r.rule,
                "condition": r.condition,
                "preset_id": r.preset_id,
                "severity": r.severity,
                "layer": r.layer,
            }
            for r in rules
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
