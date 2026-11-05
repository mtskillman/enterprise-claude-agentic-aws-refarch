"""Semantic and sliding-window text chunker for enterprise ingestion."""

from __future__ import annotations

from typing import List


class TextChunker:
    """Splits long-form documents into overlapping token-sized passages."""

    def __init__(self, chunk_size_words: int = 400, overlap_words: int = 50) -> None:
        self.chunk_size = chunk_size_words
        self.overlap = overlap_words

    def chunk(self, text: str) -> List[str]:
        words = text.split()
        if not words:
            return []

        chunks: List[str] = []
        start = 0
        while start < len(words):
            end = min(start + self.chunk_size, len(words))
            chunk_str = " ".join(words[start:end])
            chunks.append(chunk_str)
            if end == len(words):
                break
            start += self.chunk_size - self.overlap
        return chunks
