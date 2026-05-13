"""Tighten-only invariant checks for profile + per-loan config writes.

The resolver-spec.md §1 contract: a downstream layer (loan_program →
investor_overlay → per-loan) may **add** required docs / extra rules
and **raise** thresholds, but it may **not** remove required docs or
**lower** thresholds. The check happens at write time so the read-time
resolver can trust its inputs.

Returns a ``TightenOnlyViolation`` exception with the offending action
spelled out in plain English — the admin UI surfaces this verbatim as
the inline error tooltip.

Pure CPU. No I/O. Same inputs → identical output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


class TightenOnlyViolation(ValueError):
    """Raised when a profile/loan write would weaken a downstream layer.

    ``message`` is operator-facing (rendered verbatim in the admin UI
    tooltip). ``code`` is a stable identifier for tests + i18n.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── Resolved-shape inputs ─────────────────────────────────────────────


@dataclass(frozen=True)
class _ChecklistEntry:
    doc_type_key: str
    required: bool


@dataclass(frozen=True)
class _FieldOverride:
    doc_type_key: str
    field_key: str
    required: bool | None
    min_confidence: float | None


# ── Checklist tighten-only ────────────────────────────────────────────


def check_checklist_tightens(
    *,
    upstream: Iterable[_ChecklistEntry | dict[str, Any]],
    proposed: Iterable[_ChecklistEntry | dict[str, Any]],
) -> None:
    """Reject ``required=False`` on a doc type that's required upstream.

    ``upstream`` is the resolved checklist *as of now* — Global +
    higher-precedence profile rows already merged. ``proposed`` is the
    new checklist about to be persisted on this layer. Either iterable
    accepts dicts (e.g. straight from the JSONB column) or
    ``_ChecklistEntry`` objects.
    """
    up_required: set[str] = set()
    for item in upstream:
        key, req = _coerce_checklist(item)
        if key and req:
            up_required.add(key)

    for item in proposed:
        key, req = _coerce_checklist(item)
        if not key:
            continue
        if not req and key in up_required:
            raise TightenOnlyViolation(
                code="checklist_lowers_required",
                message=(
                    f"Cannot mark '{key}' as Optional — a higher-precedence "
                    f"layer requires it. To make it optional everywhere, edit "
                    f"the Global doc-type catalog."
                ),
            )


# ── Field min_confidence tighten-only ─────────────────────────────────


def check_field_overrides_tighten(
    *,
    upstream_min_confidence: dict[tuple[str, str], float],
    upstream_required: dict[tuple[str, str], bool],
    proposed_overrides: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Reject min_confidence drops or required=False on a downstream layer.

    ``upstream_min_confidence`` and ``upstream_required`` are keyed by
    ``(doc_type_key, field_key)`` and reflect the resolved value at the
    point this write would land. ``proposed_overrides`` is the
    nested-dict shape persisted on ``LOProgramProfile.extraction_overrides``.
    """
    for doc_type_key, fields in (proposed_overrides or {}).items():
        if not isinstance(fields, dict):
            continue
        for field_key, override in fields.items():
            if not isinstance(override, dict):
                continue

            mc = override.get("min_confidence")
            if isinstance(mc, (int, float)):
                upstream = upstream_min_confidence.get(
                    (doc_type_key, field_key)
                )
                if upstream is not None and float(mc) < float(upstream):
                    raise TightenOnlyViolation(
                        code="min_confidence_lowers",
                        message=(
                            f"Cannot lower min_confidence for "
                            f"{doc_type_key}.{field_key} below {upstream:.2f} — "
                            f"a higher-precedence layer set the floor."
                        ),
                    )

            req = override.get("required")
            if req is False:
                up_required = upstream_required.get(
                    (doc_type_key, field_key), False
                )
                if up_required:
                    raise TightenOnlyViolation(
                        code="field_lowers_required",
                        message=(
                            f"Cannot mark {doc_type_key}.{field_key} as "
                            f"Optional — a higher-precedence layer requires "
                            f"it. Edit the Global extraction schema instead."
                        ),
                    )


# ── Profile-shape sanity checks ───────────────────────────────────────


def check_profile_shape(*, type_: str, stacks_with: object) -> None:
    """Enforce ``investor_overlay`` ↔ ``stacks_with`` correspondence.

    Loan programs may not point at another profile; investor overlays
    must point at exactly one base loan program.
    """
    if type_ == "loan_program" and stacks_with is not None:
        raise TightenOnlyViolation(
            code="loan_program_has_stacks_with",
            message=(
                "A loan-program profile cannot stack on another profile. "
                "Set type='investor_overlay' if this is meant to overlay."
            ),
        )
    if type_ == "investor_overlay" and stacks_with is None:
        raise TightenOnlyViolation(
            code="investor_overlay_missing_stacks_with",
            message=(
                "An investor-overlay profile must point at a base "
                "loan-program via stacks_with."
            ),
        )


# ── Helpers ───────────────────────────────────────────────────────────


def _coerce_checklist(item: object) -> tuple[str | None, bool]:
    if isinstance(item, _ChecklistEntry):
        return (item.doc_type_key, item.required)
    if isinstance(item, dict):
        key = item.get("doc_type_key") or item.get("key")
        req = bool(item.get("required", False))
        if isinstance(key, str) and key:
            return (key, req)
    return (None, False)
