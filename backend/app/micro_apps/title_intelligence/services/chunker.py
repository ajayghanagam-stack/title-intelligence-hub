"""Hierarchical text chunker matching V2's paragraph → sentence → character strategy."""

import re


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """Split text into chunks with overlap, respecting paragraph and sentence boundaries.

    Strategy (matching V2):
    1. Split on paragraph boundaries (double newline)
    2. If paragraph > chunk_size, split on sentence boundaries
    3. If sentence > chunk_size, split on character boundaries
    4. Merge small consecutive chunks up to chunk_size
    5. Add overlap window from previous chunk for context preservation
    """
    if not text or not text.strip():
        return []

    paragraphs = _split_paragraphs(text)
    raw_chunks: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) <= chunk_size:
            raw_chunks.append(para)
        else:
            # Paragraph too large — split on sentences
            sentences = _split_sentences(para)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(sentence) <= chunk_size:
                    raw_chunks.append(sentence)
                else:
                    # Sentence too large — split on characters
                    raw_chunks.extend(_split_characters(sentence, chunk_size))

    # Merge small consecutive chunks up to chunk_size
    merged = _merge_chunks(raw_chunks, chunk_size)

    # Add overlap from previous chunk
    if overlap > 0 and len(merged) > 1:
        merged = _add_overlap(merged, overlap)

    return [c for c in merged if c.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split text on double newlines (paragraph boundaries)."""
    return re.split(r"\n\s*\n", text)


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries (period/question/exclamation followed by space or newline)."""
    # Match sentence-ending punctuation followed by whitespace or end of string
    parts = re.split(r"(?<=[.!?])\s+", text)
    return parts


def _split_characters(text: str, chunk_size: int) -> list[str]:
    """Split text on character boundaries, preferring word breaks."""
    chunks = []
    while len(text) > chunk_size:
        # Try to break at a space near the chunk boundary
        split_pos = text.rfind(" ", 0, chunk_size)
        if split_pos == -1 or split_pos < chunk_size // 2:
            split_pos = chunk_size
        chunks.append(text[:split_pos].strip())
        text = text[split_pos:].strip()
    if text:
        chunks.append(text)
    return chunks


def _merge_chunks(chunks: list[str], chunk_size: int) -> list[str]:
    """Merge small consecutive chunks until they approach chunk_size."""
    if not chunks:
        return []

    merged = []
    current = chunks[0]

    for chunk in chunks[1:]:
        combined = current + "\n\n" + chunk
        if len(combined) <= chunk_size:
            current = combined
        else:
            merged.append(current)
            current = chunk

    merged.append(current)
    return merged


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Prepend overlap characters from previous chunk to each subsequent chunk."""
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        # Take last `overlap` chars from previous chunk, breaking at word boundary
        if len(prev) > overlap:
            overlap_start = prev[-(overlap):]
            # Find first space to start at word boundary
            space_pos = overlap_start.find(" ")
            if space_pos != -1:
                overlap_text = overlap_start[space_pos + 1:]
            else:
                overlap_text = overlap_start
        else:
            overlap_text = prev

        result.append(overlap_text + " " + chunks[i])

    return result
