"""Tests for adaptive chunk sizing in the document grouper."""

import pytest

from app.micro_apps.title_intelligence.services.document_grouper import (
    DocumentGroup,
    compute_adaptive_batch_size,
    regroup_with_adaptive_sizes,
)


def _make_group(pages: list[int], doc_type: str = "generic") -> DocumentGroup:
    return DocumentGroup(
        group_id=0,
        start_page=pages[0],
        end_page=pages[-1],
        page_count=len(pages),
        pages=pages,
        doc_type=doc_type,
    )


class TestComputeAdaptiveBatchSize:
    """Test compute_adaptive_batch_size() logic."""

    def test_short_text_returns_near_min_size(self):
        """<200 chars avg → returns closer to min_size."""
        group = _make_group([1, 2, 3, 4, 5])
        # ~50 chars each → avg 50
        page_texts = {i: "x" * 50 for i in range(1, 6)}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert 10 <= size <= 16  # Should be closer to min_size

    def test_long_text_returns_near_max_size(self):
        """>800 chars avg → returns closer to max_size."""
        group = _make_group([1, 2, 3, 4, 5])
        page_texts = {i: "x" * 2000 for i in range(1, 6)}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert 35 <= size <= 40  # Should be closer to max_size

    def test_medium_text_returns_base_size(self):
        """200-800 chars → returns base_size."""
        group = _make_group([1, 2, 3, 4, 5])
        page_texts = {i: "x" * 500 for i in range(1, 6)}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert size == 25

    def test_empty_pages_falls_back_to_base_size(self):
        """No text → falls back to base_size."""
        group = _make_group([1, 2, 3])
        page_texts: dict[int, str] = {}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert size == 25

    def test_all_empty_strings_falls_back(self):
        """All empty strings → no usable text → falls back to base_size."""
        group = _make_group([1, 2, 3])
        page_texts = {1: "", 2: "", 3: ""}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert size == 25

    def test_deterministic_10x(self):
        """Same input 10 times → identical output."""
        group = _make_group([1, 2, 3, 4, 5])
        page_texts = {i: "x" * 300 for i in range(1, 6)}
        results = [
            compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
            for _ in range(10)
        ]
        assert all(r == results[0] for r in results)

    def test_boundary_200_chars(self):
        """Exactly 200 chars avg should return base_size."""
        group = _make_group([1, 2])
        page_texts = {1: "x" * 200, 2: "x" * 200}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert size == 25

    def test_boundary_800_chars(self):
        """Exactly 800 chars avg should return base_size."""
        group = _make_group([1, 2])
        page_texts = {1: "x" * 800, 2: "x" * 800}
        size = compute_adaptive_batch_size(group, page_texts, base_size=25, min_size=10, max_size=40)
        assert size == 25


class TestRegroupWithAdaptiveSizes:
    """Test regroup_with_adaptive_sizes() logic."""

    def test_splits_large_groups_with_long_text(self):
        """50-page group with long text → split at ~40pp not 25pp."""
        pages = list(range(1, 51))
        group = _make_group(pages)
        page_texts = {i: "x" * 2000 for i in pages}

        result = regroup_with_adaptive_sizes(
            [group], page_texts, base_size=25, min_size=10, max_size=40,
        )
        # Adaptive size for long text → 40. So 50 pages → 2 groups (40+10)
        assert len(result) == 2
        assert result[0].page_count == 40
        assert result[1].page_count == 10

    def test_keeps_small_groups_unchanged(self):
        """Groups already under adaptive size → unchanged."""
        group = _make_group([1, 2, 3, 4, 5])
        page_texts = {i: "x" * 500 for i in range(1, 6)}

        result = regroup_with_adaptive_sizes(
            [group], page_texts, base_size=25, min_size=10, max_size=40,
        )
        assert len(result) == 1
        assert result[0].pages == [1, 2, 3, 4, 5]

    def test_with_no_page_texts(self):
        """All empty → falls back to base_size splitting."""
        pages = list(range(1, 51))
        group = _make_group(pages)
        page_texts: dict[int, str] = {}

        result = regroup_with_adaptive_sizes(
            [group], page_texts, base_size=25, min_size=10, max_size=40,
        )
        # base_size=25, so 50 pages → 2 groups (25+25)
        assert len(result) == 2
        assert result[0].page_count == 25
        assert result[1].page_count == 25

    def test_short_text_splits_into_smaller_chunks(self):
        """Short text (<200 chars) → smaller adaptive size → more groups."""
        pages = list(range(1, 31))
        group = _make_group(pages)
        # Very short text: avg ~50 chars → adaptive size ~14
        page_texts = {i: "x" * 50 for i in pages}

        result = regroup_with_adaptive_sizes(
            [group], page_texts, base_size=25, min_size=10, max_size=40,
        )
        # Adaptive size ~14, so 30 pages → 3 groups (14+14+2)
        assert len(result) >= 2
        assert all(g.page_count <= 15 for g in result)

    def test_multiple_groups_independent(self):
        """Each group gets its own adaptive size based on its text."""
        group_short = _make_group(list(range(1, 21)))
        group_long = _make_group(list(range(21, 51)))

        page_texts = {}
        # Short text for first group
        for i in range(1, 21):
            page_texts[i] = "x" * 50
        # Long text for second group
        for i in range(21, 51):
            page_texts[i] = "x" * 2000

        result = regroup_with_adaptive_sizes(
            [group_short, group_long], page_texts, base_size=25, min_size=10, max_size=40,
        )
        # group_short: 20 pages, adaptive ~14 → split into ~2 sub-groups
        # group_long: 30 pages, adaptive ~40 → stays as 1 group
        short_groups = [g for g in result if g.start_page < 21]
        long_groups = [g for g in result if g.start_page >= 21]
        assert len(short_groups) >= 2
        assert len(long_groups) == 1

    def test_group_ids_sequential(self):
        """Output group IDs should be 0-based sequential."""
        groups = [
            _make_group(list(range(1, 51))),
            _make_group(list(range(51, 61))),
        ]
        page_texts = {i: "x" * 500 for i in range(1, 61)}

        result = regroup_with_adaptive_sizes(
            groups, page_texts, base_size=25, min_size=10, max_size=40,
        )
        assert [g.group_id for g in result] == list(range(len(result)))

    def test_preserves_doc_type(self):
        """Split sub-groups inherit parent's doc_type."""
        pages = list(range(1, 51))
        group = _make_group(pages, doc_type="schedule_b2")
        page_texts = {i: "x" * 2000 for i in pages}

        result = regroup_with_adaptive_sizes(
            [group], page_texts, base_size=25, min_size=10, max_size=40,
        )
        assert all(g.doc_type == "schedule_b2" for g in result)
