"""Monotonic pipeline-stage advance contract (PRD §3.5).

The Phase 3 contract is simple: ``loan.pipeline_stage`` only ever moves
*forward* in the canonical stage order. A remediation child workflow
that re-runs an earlier stage (classify, doc_validation, extract) must
not rewind the loan's overall progress — the operator already advanced
past those stages once, and the doc-validation page only stops looking
at hard stops once the loan has crossed into ``extract`` territory.

This module is the single source of truth for that ordering. Callers
write target stages through ``advance_stage`` (or
``mark_pipeline_status`` which routes through it). A backwards write
is silently coerced to the current stage — a `ValueError` would force
every callsite to thread try/except, and the spec is explicit that
"no-op" is the right behavior, not "fail".

Phase 4 introduces new stage names (``doc_validation``,
``data_validation``, ``decision_ready``); we expose the *target* order
today so the contract is in place before the rename. Aliases for the
current LO stage names (``stack``, ``validate``, ``review``,
``complete``) keep ``mark_pipeline_status`` callsites working
unchanged.
"""
from __future__ import annotations

from typing import Iterable

# Canonical Phase 4 stage order. Keep in sync with PRD §3.1; anything
# new lands in this tuple in the position where it actually runs.
STAGE_ORDER: tuple[str, ...] = (
    "ingest",
    "classify",
    "doc_validation",
    "extract",
    "data_validation",
    "decision_ready",
    "complete",
)

# Backwards-compat aliases for the *current* LO stage names. Any callsite
# that still writes "stack"/"validate"/"review" gets mapped to the
# Phase 4 equivalent for ordering purposes. The actual rename happens
# in Phase 4; this map keeps the contract enforceable today.
_STAGE_ALIAS: dict[str, str] = {
    # "stack" was a separate substep that has already merged into
    # classify per PRD §3.1; treat any "stack" write as classify.
    "stack": "classify",
    # Today's "validate" is the doc-level preset eval — that becomes
    # doc_validation in Phase 4.
    "validate": "doc_validation",
    # Today's "review" is the implicit transition to decision_ready.
    "review": "decision_ready",
}

# Terminal stages that don't participate in monotonic ordering — once
# a package is "failed" or "complete" the stage is frozen and any
# further write is the caller's explicit re-trigger.
_TERMINAL: frozenset[str] = frozenset({"complete", "failed"})


def _normalize(stage: str | None) -> str | None:
    """Map an alias to its canonical Phase 4 stage name."""
    if stage is None:
        return None
    return _STAGE_ALIAS.get(stage, stage)


def stage_index(stage: str | None) -> int:
    """Return the canonical position of ``stage`` in ``STAGE_ORDER``.

    Returns -1 for an unknown / None stage so unknown writes always
    appear "before" any known stage (i.e. they will not block an
    advance).
    """
    canonical = _normalize(stage)
    if canonical is None:
        return -1
    try:
        return STAGE_ORDER.index(canonical)
    except ValueError:
        return -1


def is_monotonic_advance(current: str | None, target: str | None) -> bool:
    """True if writing ``target`` over ``current`` advances or holds.

    ``None → anything`` is always an advance (the package was in an
    unknown state). A terminal current stage rejects every move.
    """
    if target is None:
        return True  # no-op write — caller isn't actually advancing
    if current in _TERMINAL:
        return False
    return stage_index(target) >= stage_index(current)


def advance_stage(current: str | None, target: str | None) -> str | None:
    """Return the stage to persist: ``target`` if forward, else ``current``.

    Pure function — no side effects, safe to call in tight loops or
    property-based tests. Use it as a gate immediately before writing
    ``LOPackage.pipeline_stage``:

        next_stage = advance_stage(pkg.pipeline_stage, "doc_validation")
        if next_stage != pkg.pipeline_stage:
            pkg.pipeline_stage = next_stage
    """
    if target is None:
        return current
    if is_monotonic_advance(current, target):
        return target
    return current


def is_terminal(stage: str | None) -> bool:
    """True if ``stage`` is a frozen terminal (``complete``/``failed``)."""
    return stage in _TERMINAL


def all_known_stages() -> Iterable[str]:
    """Iterate over every canonical stage + every alias.

    Useful for property-based tests that want to fuzz over the full
    domain of legal stage strings.
    """
    yield from STAGE_ORDER
    yield from _STAGE_ALIAS.keys()
