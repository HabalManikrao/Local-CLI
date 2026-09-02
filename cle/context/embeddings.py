"""Local semantic embeddings.

Builds embeddings for source chunks via the provider's embedding model and
stores them in the index database. Similarity search uses cosine distance
(pure-Python, dependency-free; FAISS is an optional future acceleration noted
in the audit). Everything stays local and offline.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

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
    dot = sum(x * y for x, y in zip(a, b))
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

    def build(self, root: Path, window: int = 60, overlap: int = 10) -> int:
        """Embed all eligible chunks under *root*. Returns chunk count."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM embeddings")
        count = 0
        with self.db.transaction() as conn:
            for path in iter_source_files(root):
                language = detect_language(path)
                if language not in _EMBED_LANGUAGES:
                    continue
                try:
                    if path.stat().st_size > _MAX_EMBED_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel = path.relative_to(root).as_posix()
                for chunk in chunk_text(rel, text, window, overlap):
                    vector = self.provider.embed(self.model, chunk.text)
                    conn.execute(
                        "INSERT INTO embeddings(path, start, end, text, model, dim, vector) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (chunk.path, chunk.start, chunk.end, chunk.text,
                         self.model, len(vector), json.dumps(vector)),
                    )
                    count += 1
        self.db.set_meta("embeddings_model", self.model)
        return count

    def search(self, query: str, top_k: int = 8) -> list[SemanticHit]:
        """Return the *top_k* chunks most similar to *query*."""
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
