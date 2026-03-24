"""Tests for hierarchical text chunker."""

import pytest

from app.micro_apps.title_intelligence.services.chunker import chunk_text


def test_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text():
    """Text shorter than chunk_size should return a single chunk."""
    text = "Hello, this is a short paragraph."
    result = chunk_text(text, chunk_size=500, overlap=50)
    assert len(result) == 1
    assert "Hello" in result[0]


def test_paragraph_splitting():
    """Text with paragraphs should split on paragraph boundaries."""
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    result = chunk_text(text, chunk_size=30, overlap=0)
    assert len(result) >= 2


def test_sentence_splitting():
    """Long paragraphs should split on sentence boundaries."""
    text = "First sentence is here. Second sentence follows. Third sentence ends it."
    result = chunk_text(text, chunk_size=40, overlap=0)
    assert len(result) >= 2


def test_character_splitting():
    """Very long sentences should split on character boundaries."""
    text = "a" * 1000  # No spaces or sentences
    result = chunk_text(text, chunk_size=100, overlap=0)
    assert len(result) >= 10


def test_overlap():
    """Chunks should have overlap from previous chunk."""
    text = "First paragraph with some content.\n\nSecond paragraph with more content.\n\nThird paragraph final."
    result = chunk_text(text, chunk_size=40, overlap=10)
    if len(result) > 1:
        # Second chunk should start with overlap from first
        assert len(result[1]) > len("Second paragraph with more content.")


def test_respects_word_boundaries():
    """Character splitting should prefer word boundaries."""
    text = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12"
    result = chunk_text(text, chunk_size=30, overlap=0)
    for chunk in result:
        # No chunk should start or end mid-word (unless very long word)
        assert not chunk.startswith(" ")


def test_min_chunk_filtering():
    """Very short chunks (< 10 chars) are filtered in stage_index, not in chunker."""
    text = "A.\n\nB.\n\nLonger paragraph with content."
    result = chunk_text(text, chunk_size=500, overlap=0)
    # Chunker keeps all chunks; stage_index filters
    assert len(result) >= 1


def test_real_title_text():
    """Test with realistic title document text."""
    text = """SCHEDULE A

    1. Effective Date: January 15, 2024
    2. Policy Amount: $500,000.00
    3. The estate or interest in the land described herein and which is covered by this Commitment is: Fee Simple

    Name of Proposed Insured: John Smith and Jane Smith, as Joint Tenants

    The land referred to in this Commitment is described as follows:
    Lot 15, Block 3, of SUNSHINE ESTATES, according to the map thereof filed in Book 45, Page 12.

    SCHEDULE B-I REQUIREMENTS

    1. Payment of the full consideration to, or for the account of, the grantors or mortgagors.
    2. Instruments creating the estate or interest to be insured must be recorded.
    3. Payment of all taxes and assessments due and payable."""

    result = chunk_text(text, chunk_size=500, overlap=50)
    assert len(result) >= 1
    # All original content should be present across chunks
    combined = " ".join(result)
    assert "SCHEDULE A" in combined
    assert "John Smith" in combined
    assert "REQUIREMENTS" in combined
