"""Chunking: split source files into overlapping line windows for embedding.

Windows keep line ranges so retrieved chunks map back to exact locations
(provenance requirement, §5/§10). Chunking is symbol-agnostic here; structural
retrieval is handled separately via the symbol index.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    path: str
    start: int   # 1-based first line
    end: int     # 1-based last line (inclusive)
    text: str


def chunk_text(path: str, text: str, window: int = 60, overlap: int = 10) -> list[Chunk]:
    """Split *text* into line windows of *window* lines with *overlap*."""
    lines = text.splitlines()
    if not lines:
        return []
    if overlap >= window:
        overlap = window // 2
    step = window - overlap
    chunks: list[Chunk] = []
    i = 0
    n = len(lines)
    while i < n:
        window_lines = lines[i : i + window]
        start = i + 1
        end = i + len(window_lines)
        body = "\n".join(window_lines).strip()
        if body:
            chunks.append(Chunk(path=path, start=start, end=end, text=body))
        if i + window >= n:
            break
        i += step
    return chunks
