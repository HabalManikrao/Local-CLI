"""Local semantic embeddings.

Builds embeddings for source chunks via the provider's embedding model and
stores them in the index database. Similarity search uses cosine distance
(pure-Python, dependency-free; FAISS is an optional future acceleration noted
in the audit). Everything stays local and offline.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..errors import ProviderError
from ..indexing.database import IndexDatabase
from ..indexing.repository import iter_source_files
from ..indexing.symbols import detect_language
from ..models.base import ModelProvider
from .chunker import chunk_text

# Languages worth embedding (code + docs). Others are skipped.
_EMBED_LANGUAGES = {
    "java", "python", "javascript", "typescript", "kotlin", "go", "ruby",
    "csharp", "markdown",
}
_MAX_EMBED_BYTES = 500_000


@dataclass
class SemanticHit:
    path: str
    start: int
    end: int
    text: str
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingStore:
    def __init__(self, db: IndexDatabase, provider: ModelProvider, model: str):
        self.db = db
        self.provider = provider
        self.model = model

    def build(
        self,
        root: Path,
        window: int = 60,
        overlap: int = 10,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Embed all eligible chunks under *root*. Returns chunk count.

        ``on_progress(done, total, rel)`` is called after each file so callers
        can show progress — a real repo + model is many minutes of work. Each
        file's rows are written in their own transaction and embedding calls run
        *outside* the DB lock, so a long embed never holds a write lock across
        thousands of HTTP round-trips.
        """
        candidates = [
            p for p in iter_source_files(root)
            if detect_language(p) in _EMBED_LANGUAGES
        ]
        total = len(candidates)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM embeddings")
        count = 0
        for done, path in enumerate(candidates, start=1):
            rel = path.relative_to(root).as_posix()
            try:
                if path.stat().st_size <= _MAX_EMBED_BYTES:
                    text = path.read_text(encoding="utf-8")
                    # Embed every chunk first (network I/O, no DB lock held)...
                    rows = []
                    for chunk in chunk_text(rel, text, window, overlap):
                        vector = self.provider.embed(self.model, chunk.text)
                        rows.append((
                            chunk.path, chunk.start, chunk.end, chunk.text,
                            self.model, len(vector), json.dumps(vector),
                        ))
                    # ...then commit this file's rows in a single short tx.
                    if rows:
                        with self.db.transaction() as conn:
                            conn.executemany(
                                "INSERT INTO embeddings"
                                "(path, start, end, text, model, dim, vector) "
                                "VALUES(?,?,?,?,?,?,?)",
                                rows,
                            )
                        count += len(rows)
            except (OSError, UnicodeDecodeError):
                pass
            if on_progress is not None:
                on_progress(done, total, rel)
        self.db.set_meta("embeddings_model", self.model)
        return count

    def search(self, query: str, top_k: int = 8) -> list[SemanticHit]:
        """Return the *top_k* chunks most similar to *query*."""
        # Vectors are only comparable to a query embedded with the SAME model.
        # If the configured model changed since `cle embed`, dimensions differ
        # and every cosine would be 0.0 — silently blinding retrieval. Fail loud.
        built_model = self.db.get_meta("embeddings_model")
        if built_model and built_model != self.model:
            raise ProviderError(
                f"Semantic index was built with embedding model '{built_model}', "
                f"but '{self.model}' is now configured; similarity would be "
                f"meaningless.",
                remedy="Rebuild the semantic index:\n  cle embed",
            )
        rows = self.db.execute(
            "SELECT path, start, end, text, vector FROM embeddings"
        ).fetchall()
        if not rows:
            return []
        qvec = self.provider.embed(self.model, query)
        scored: list[SemanticHit] = []
        for r in rows:
            vec = json.loads(r["vector"])
            scored.append(SemanticHit(
                path=r["path"], start=r["start"], end=r["end"],
                text=r["text"], score=_cosine(qvec, vec),
            ))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    def is_built(self) -> bool:
        row = self.db.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        return int(row[0]) > 0
