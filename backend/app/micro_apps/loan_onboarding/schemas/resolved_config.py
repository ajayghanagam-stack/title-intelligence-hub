"""Frozen dataclasses for the Phase 2 ``effective_config(loan_id)`` resolver.

These are *value objects* — every field is final after construction so
the resolver's output can be:

  - cached safely in a process-local LRU (no shared mutable state),
  - hashed deterministically into a ``config_hash`` that downstream AI
    cache keys depend on,
  - passed across coroutines without defensive copies.

See ``docs/phase0/resolver-spec.md`` §3 for the full spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


# ── Layer-tagged source for resolved rules ───────────────────────────


ResolvedLayer = Literal["global", "loan_program", "investor_overlay", "loan"]


# ── Doc-type catalog row, fully resolved ─────────────────────────────


@dataclass(frozen=True)
class ResolvedDocType:
    """One doc-type after Global → program → overlay → loan stacking."""

    key: str
    name: str
    category: str
    required: bool
    expected_min_pages: int | None
    expected_max_pages: int | None
    auto_classify_enabled: bool


# ── Field schema row, fully resolved ─────────────────────────────────


@dataclass(frozen=True)
class ResolvedField:
    """One extraction field for a doc type, after profile/loan overrides."""

    key: str
    label: str
    data_type: str  # "string"|"currency"|"date"|"ssn"|"phone"|"email"|"address"|"boolean"
    required: bool
    min_confidence: float
    regex: str | None = None
    alias: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedSchema:
    """Per-doc-type extraction schema after all layers stack."""

    doc_type_key: str
    schema_version: int  # bumped on every org-level edit; folds into config_hash
    fields: tuple[ResolvedField, ...]


# ── Validation rule, layer-tagged ────────────────────────────────────


@dataclass(frozen=True)
class ResolvedRule:
    """One validation rule with the layer that contributed it.

    The ``layer`` tag exists for observability (the operator UI tints
    profile-added rules differently from loan-level ones); it does not
    affect rule semantics.
    """

    scope: str  # "package" | "doc_type:{key}"
    rule: str
    condition: str
    preset_id: str | None
    severity: Literal["hard", "soft"]
    layer: ResolvedLayer


# ── The thing the resolver returns ───────────────────────────────────


@dataclass(frozen=True)
class EffectiveConfig:
    """Frozen, hashable, fully-resolved config for one loan.

    Hashable because every field is either immutable (str/int/UUID/None)
    or already a tuple of frozen dataclasses. ``config_hash`` is
    computed by ``services/config_resolver.py`` over a canonical JSON
    form — same inputs → identical hash, regardless of dict ordering.

    Downstream AI cache keys fold ``config_hash`` in so a profile edit
    or a per-loan override automatically misses cache.
    """

    loan_id: UUID
    org_id: UUID
    program_profile_id: UUID | None
    investor_overlay_id: UUID | None  # set only when profile is an overlay

    doc_types: tuple[ResolvedDocType, ...]
    schemas_by_doc_type: tuple[ResolvedSchema, ...]
    rules: tuple[ResolvedRule, ...]

    config_hash: str  # SHA-256 hex; deterministic
    grounding_contract_version: str  # = GROUNDING_CONTRACT_VERSION

    # ── Convenience accessors (no logic — purely ergonomic) ─────────

    def doc_type(self, key: str) -> ResolvedDocType | None:
        for d in self.doc_types:
            if d.key == key:
                return d
        return None

    def schema(self, doc_type_key: str) -> ResolvedSchema | None:
        for s in self.schemas_by_doc_type:
            if s.doc_type_key == doc_type_key:
                return s
        return None

    def required_doc_types(self) -> tuple[ResolvedDocType, ...]:
        return tuple(d for d in self.doc_types if d.required)

    def allowed_doc_type_keys(self) -> tuple[str, ...]:
        """Keys the page classifier is allowed to predict — drives the
        classifier's enum and the ``Others`` fallback rule."""
        return tuple(
            d.key for d in self.doc_types
            if d.auto_classify_enabled
        )
