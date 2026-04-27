"""Deterministic stacking: one stack per predicted doc_type.

No LLM calls — this is a pure, byte-stable function of the classification
output. A "stack" represents a single document in the loan package: all pages
sharing the same `predicted_doc_type` collapse into exactly one stack,
regardless of whether their page_numbers are contiguous.

Why merge non-contiguous runs? Gemini's per-page classifier occasionally drops
a mid-document page into `Others` (blank/signature/transmittal boilerplate)
and then picks the original doc_type back up on the next page, or flags each
classifier-chunk boundary with a fresh `first_page` marker. Treating each run
as its own stack produces duplicates in the UI — e.g. two "Title Commitment"
entries and two "Others" entries for what the user experiences as one title
commitment with a couple of junk pages. The reviewer's mental model is
"one entry per document type in the package," so we group that way.

Trade-off: if a package genuinely contains multiple instances of the same
doc_type (e.g. three monthly paystubs), they all land in one PAYSTUB stack
containing all paystub pages. The reviewer can still drill into individual
pages via the stack card, and the `split_accuracy` heuristic in
`confidence_scorer.py` will correctly penalise a stack with multiple
`first_page` markers — which keeps such stacks routed to HITL.

The reserved `Others` bucket is grouped the same way: all Others pages across
the entire package live in one Others stack. Downstream validate/review
stages treat Others stacks conservatively (they do not contribute to required
doc-type coverage and are always routed to HITL).

Stack ordering: stack_index is assigned in order of the doc_type's *first*
page appearance, so the UI renders stacks roughly in reading order.

Confidence rollup:
- `classification_confidence` = mean of per-page confidences
- A stack is flagged `requires_hitl=True` if:
    - its `classification_confidence` is below `hitl_threshold`, OR
    - its doc_type is the reserved `Others` bucket (we never auto-accept
      unmatched content)

Outputs are plain dicts so the caller can decide whether to materialise as
SQLAlchemy rows or use them in-memory (useful for tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY


@dataclass(frozen=True)
class ClassifiedPage:
    """Minimal shape required to build stacks.

    Use this instead of the full ORM row so tests can build fixtures cheaply.
    """
    page_number: int
    predicted_doc_type: str
    confidence: float
    page_role: str = "unknown"


@dataclass
class StackDraft:
    """In-memory stack before it is persisted as an LOStack row."""
    stack_index: int
    doc_type: str
    page_numbers: list[int]
    first_page: int
    last_page: int
    classification_confidence: float
    requires_hitl: bool
    status: str = "classified"


def build_stacks(
    classifications: Iterable[ClassifiedPage | dict],
    hitl_threshold: float = 0.96,
) -> list[StackDraft]:
    """Group all pages sharing a `predicted_doc_type` into a single stack.

    Stacks are emitted in order of the doc_type's first page appearance.
    Within each stack, `page_numbers` is sorted ascending. Input is sorted
    defensively so callers can pass rows in any order.
    """
    pages = [_coerce_page(p) for p in classifications]
    pages.sort(key=lambda p: p.page_number)

    # Group by doc_type, preserving first-occurrence order so stack_index is
    # deterministic and roughly matches reading order in the source PDF.
    groups: dict[str, list[ClassifiedPage]] = {}
    order: list[str] = []
    for p in pages:
        if p.predicted_doc_type not in groups:
            groups[p.predicted_doc_type] = []
            order.append(p.predicted_doc_type)
        groups[p.predicted_doc_type].append(p)

    stacks: list[StackDraft] = []
    for idx, doc_type in enumerate(order):
        members = groups[doc_type]
        # Members are already in page_number order (inherited from the sorted
        # `pages` pass above), so member[0] / member[-1] give the min/max.
        page_nums = [p.page_number for p in members]
        confidences = [p.confidence for p in members]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        # Others stacks always require HITL — we never auto-accept unmatched content.
        needs_hitl = doc_type == OTHERS_KEY or avg_conf < hitl_threshold
        stacks.append(StackDraft(
            stack_index=idx,
            doc_type=doc_type,
            page_numbers=page_nums,
            first_page=page_nums[0],
            last_page=page_nums[-1],
            classification_confidence=round(avg_conf, 6),
            requires_hitl=needs_hitl,
        ))
    return stacks


def _coerce_page(raw: ClassifiedPage | dict) -> ClassifiedPage:
    if isinstance(raw, ClassifiedPage):
        return raw
    return ClassifiedPage(
        page_number=int(raw["page_number"]),
        predicted_doc_type=str(raw["predicted_doc_type"]),
        confidence=float(raw.get("confidence", 0.0)),
        page_role=str(raw.get("page_role") or "unknown"),
    )
