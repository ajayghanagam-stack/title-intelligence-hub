"""Rules-based document grouper for title commitment packages.

Groups consecutive content pages into logical documents using triage
page_type hints and heuristic boundary rules. Non-content pages (blank,
cover, transmittal, signature) act as natural document boundaries.

Groups are bounded by max_chunk_size to stay within LLM context limits.
Large documents that exceed max_chunk_size are split at the boundary.

This replaces arbitrary fixed-size chunking with document-aligned chunks,
ensuring related pages (e.g., a multi-page deed) are processed together.
"""

import logging
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Page types that signal document boundaries
BOUNDARY_TYPES = frozenset({"blank", "cover", "transmittal"})

# Page types that signal the end of a document (but don't start a new one)
TRAILING_TYPES = frozenset({"signature", "boilerplate"})


class DocumentGroup(BaseModel):
    """A group of related pages forming a logical document unit."""

    group_id: int = Field(description="0-based group index")
    start_page: int = Field(description="First page number (1-based, original numbering)")
    end_page: int = Field(description="Last page number (1-based, original numbering)")
    page_count: int = Field(description="Number of content pages in this group")
    pages: list[int] = Field(
        description="List of content page numbers (1-based, original numbering)"
    )
    doc_type: str = Field(
        default="generic",
        description="Document type for specialized extraction routing (majority vote from page hints)",
    )


class GroupingResult(BaseModel):
    """Result of document grouping."""

    groups: list[DocumentGroup] = Field(default_factory=list)
    total_content_pages: int = 0
    total_groups: int = 0


def _resolve_doc_type(doc_type_hints: list[str]) -> str:
    """Determine group doc_type by majority vote from page hints.

    Returns "generic" if no hints or if there's a tie including "generic".
    """
    if not doc_type_hints:
        return "generic"
    # Filter out "generic" for voting — only count specific types
    specific = [dt for dt in doc_type_hints if dt != "generic"]
    if not specific:
        return "generic"
    counts = Counter(specific)
    winner, _ = counts.most_common(1)[0]
    return winner


def group_pages(
    page_types: list[dict[str, Any]],
    max_chunk_size: int = 25,
) -> GroupingResult:
    """Group pages into logical document units based on triage page_types.

    Rules:
    1. Consecutive 'content' pages belong to the same group.
    2. 'blank' or 'cover' or 'transmittal' pages break groups (boundary).
    3. 'signature' and 'boilerplate' pages are included with the preceding
       content group (they trail a document, don't start a new one).
    4. Groups exceeding max_chunk_size are split at the size boundary.
    5. If no triage was run, all pages are content and get split by size.
    6. Each group is assigned a doc_type via majority vote from page hints.

    Args:
        page_types: List of dicts with 'page_number', 'page_type', and
            optional 'document_type_hint' keys, sorted by page_number.
            Includes ALL pages (content + non-content).
        max_chunk_size: Maximum pages per group (default 25).

    Returns:
        GroupingResult with document groups containing only content page numbers.
    """
    if not page_types:
        return GroupingResult()

    # Sort by page number to ensure correct ordering
    sorted_pages = sorted(page_types, key=lambda p: p["page_number"])

    groups: list[DocumentGroup] = []
    current_content_pages: list[int] = []
    current_doc_type_hints: list[str] = []

    def _flush_group() -> None:
        """Emit the current group if it has content pages."""
        nonlocal current_content_pages, current_doc_type_hints
        if not current_content_pages:
            current_doc_type_hints = []
            return

        doc_type = _resolve_doc_type(current_doc_type_hints)

        # Split oversized groups
        for chunk_start in range(0, len(current_content_pages), max_chunk_size):
            chunk = current_content_pages[chunk_start:chunk_start + max_chunk_size]
            groups.append(DocumentGroup(
                group_id=len(groups),
                start_page=chunk[0],
                end_page=chunk[-1],
                page_count=len(chunk),
                pages=chunk,
                doc_type=doc_type,
            ))

        current_content_pages = []
        current_doc_type_hints = []

    for page_info in sorted_pages:
        pn = page_info["page_number"]
        pt = page_info.get("page_type", "content")
        dt = page_info.get("document_type_hint", "generic")

        if pt == "content":
            current_content_pages.append(pn)
            current_doc_type_hints.append(dt)
        elif pt in BOUNDARY_TYPES:
            # Boundary page — flush current group and start fresh
            _flush_group()
        elif pt in TRAILING_TYPES:
            # Trailing page (signature, boilerplate) — stays with current group
            # but don't add to content pages (not sent to examiner)
            pass
        else:
            # Unknown type — treat as content (conservative)
            current_content_pages.append(pn)
            current_doc_type_hints.append(dt)

    # Flush any remaining pages
    _flush_group()

    total_content = sum(g.page_count for g in groups)
    doc_type_summary = Counter(g.doc_type for g in groups)
    logger.info(
        f"Document grouping: {len(sorted_pages)} pages → "
        f"{len(groups)} groups, {total_content} content pages, "
        f"doc_types: {dict(doc_type_summary)}"
    )

    return GroupingResult(
        groups=groups,
        total_content_pages=total_content,
        total_groups=len(groups),
    )


def groups_to_page_ranges(groups: list[DocumentGroup]) -> list[tuple[int, int]]:
    """Convert document groups to page ranges for the examiner.

    Each group's pages may not be strictly sequential (if non-content pages
    were interspersed). This returns the tight (min, max) range for each group.

    For use with the content-only PDF where pages are renumbered sequentially,
    this function should be called AFTER remapping to filtered PDF positions.

    Args:
        groups: List of DocumentGroup objects.

    Returns:
        List of (start_page, end_page) tuples, 1-based inclusive.
    """
    return [(g.start_page, g.end_page) for g in groups]


def groups_to_doc_types(groups: list[DocumentGroup]) -> list[str]:
    """Extract doc_type for each group, aligned with groups_to_page_ranges output.

    Args:
        groups: List of DocumentGroup objects.

    Returns:
        List of doc_type strings, one per group.
    """
    return [g.doc_type for g in groups]


def compute_adaptive_batch_size(
    group: DocumentGroup,
    page_texts: dict[int, str],
    base_size: int = 40,
    min_size: int = 20,
    max_size: int = 50,
) -> int:
    """Compute optimal batch size based on average text complexity of pages.

    Short text (<200 chars avg) → complex/scanned pages → smaller batches (closer to min_size).
    Medium text (200-800 chars avg) → normal → base_size.
    Long text (>800 chars avg) → simple text-heavy → larger batches (closer to max_size).

    Pure function, deterministic: same inputs → same output.
    """
    # Only consider pages that have entries in page_texts
    texts = [page_texts[pn] for pn in group.pages if pn in page_texts and page_texts[pn]]
    if not texts:
        return base_size

    avg_len = sum(len(t) for t in texts) / len(texts)

    if avg_len < 200:
        # Linear interpolation: 0 → min_size, 200 → base_size
        ratio = avg_len / 200.0
        return max(min_size, round(min_size + ratio * (base_size - min_size)))
    elif avg_len > 800:
        # Linear interpolation: 800 → base_size, 2000 → max_size (capped)
        ratio = min(1.0, (avg_len - 800) / 1200.0)
        return min(max_size, round(base_size + ratio * (max_size - base_size)))
    else:
        return base_size


def regroup_with_adaptive_sizes(
    groups: list[DocumentGroup],
    page_texts: dict[int, str],
    base_size: int = 40,
    min_size: int = 20,
    max_size: int = 50,
) -> list[DocumentGroup]:
    """Re-split groups that exceed their adaptive batch size.

    For each group, computes the adaptive size based on page text complexity.
    If the group is already within the adaptive size, it's kept as-is.
    If it exceeds the adaptive size, it's split into sub-groups.

    Returns a new list of DocumentGroup objects with sequential group_ids.
    """
    result: list[DocumentGroup] = []

    for group in groups:
        adaptive_size = compute_adaptive_batch_size(
            group, page_texts, base_size=base_size, min_size=min_size, max_size=max_size
        )

        if group.page_count <= adaptive_size:
            result.append(DocumentGroup(
                group_id=len(result),
                start_page=group.start_page,
                end_page=group.end_page,
                page_count=group.page_count,
                pages=group.pages,
                doc_type=group.doc_type,
            ))
        else:
            # Split into sub-groups of adaptive_size
            for chunk_start in range(0, len(group.pages), adaptive_size):
                chunk = group.pages[chunk_start:chunk_start + adaptive_size]
                result.append(DocumentGroup(
                    group_id=len(result),
                    start_page=chunk[0],
                    end_page=chunk[-1],
                    page_count=len(chunk),
                    pages=chunk,
                    doc_type=group.doc_type,
                ))

    if result != groups:
        logger.info(
            f"Adaptive chunk sizing: {len(groups)} groups → {len(result)} groups"
        )

    return result


def remap_groups_to_filtered_pdf(
    groups: list[DocumentGroup],
    content_page_map_inverse: dict[int, int],
) -> list[DocumentGroup]:
    """Remap group page numbers from original PDF to content-only PDF positions.

    When triage filters non-content pages, the content-only PDF has different
    page numbering. This function translates group page references to the
    filtered PDF's numbering.

    Args:
        groups: Groups with original page numbers.
        content_page_map_inverse: Mapping from original page number → position
            in content-only PDF (1-based).

    Returns:
        New list of DocumentGroup objects with remapped page numbers.
    """
    remapped = []
    for g in groups:
        new_pages = []
        for pn in g.pages:
            mapped = content_page_map_inverse.get(pn)
            if mapped is not None:
                new_pages.append(mapped)
        if new_pages:
            remapped.append(DocumentGroup(
                group_id=len(remapped),
                start_page=new_pages[0],
                end_page=new_pages[-1],
                page_count=len(new_pages),
                pages=new_pages,
                doc_type=g.doc_type,
            ))
    return remapped
