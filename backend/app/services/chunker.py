"""Text chunking utility for embedding generation."""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: Input text to chunk
        chunk_size: Maximum characters per chunk
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        # Try to break at a sentence boundary if possible
        if end < text_len:
            # Look for sentence ending within the last 100 chars of the chunk
            search_start = max(start, end - 100)
            sentence_end = _find_sentence_boundary(text, search_start, end)
            if sentence_end > start:
                end = sentence_end

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        # Move start position with overlap
        start = end - overlap
        if start < 0:
            start = 0

    return chunks


def _find_sentence_boundary(text: str, search_start: int, search_end: int) -> int:
    """Find the last sentence boundary (., !, ?) within the search range."""
    # Look for sentence endings
    for i in range(search_end - 1, search_start - 1, -1):
        if text[i] in ".!?":
            # Check if followed by whitespace or end of string
            if i + 1 >= len(text) or text[i + 1].isspace():
                return i + 1
    return search_end