"""Retrieval engine — combine exact, structural, and semantic search into a
ranked, provenance-tagged context set.

Every :class:`ContextItem` retains file, line range, symbol, type, a relevance
score, the reason it was selected, and an evidence source (always LOCAL here),
satisfying the context-provenance requirement (§5/§10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..errors import CleError
from ..evidence import EvidenceSource
from ..indexing.repository import RepositoryIndex
from ..models.base import ModelProvider
from ..models.registry import ModelRegistry
from .embeddings import EmbeddingStore
from ..tools.search import SearchMatch, search as exact_search

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


@dataclass
class ContextItem:
    path: str
    line_start: int
    line_end: int
    kind: str                 # symbol kind or "chunk"
    symbol: str | None
    relevance: float
    reason: str
    source: EvidenceSource = EvidenceSource.LOCAL
    text: str = ""

    def location(self) -> str:
        span = f"{self.line_start}-{self.line_end}" if self.line_end else str(self.line_start)
        return f"{self.path}:{span}"


class ContextEngine:
    def __init__(
        self,
        root: Path,
        index: RepositoryIndex,
        provider: ModelProvider,
        registry: ModelRegistry,
        config: Config,
    ):
        self.root = root
        self.index = index
        self.provider = provider
        self.registry = registry
        self.config = config

    # -- individual modes ---------------------------------------------------

    def search_exact(self, pattern: str, **kw) -> list[SearchMatch]:
        return exact_search(self.root, pattern, **kw)

    def search_symbols(self, name: str, kind: str | None = None) -> list[dict]:
        return self.index.find_symbols(name, kind)

    def _embedding_store(self) -> EmbeddingStore | None:
        """Return an EmbeddingStore if an embedding model is configured."""
        model = self.config.get("models.embedding", "") or ""
        if not model:
            return None
        return EmbeddingStore(self.index.db, self.provider, model)

    def search_semantic(self, query: str, top_k: int = 8):
        store = self._embedding_store()
        if store is None or not store.is_built():
            return []
        return store.search(query, top_k)

    # -- combined retrieval -------------------------------------------------

    def retrieve(self, query: str, max_items: int | None = None) -> list[ContextItem]:
        """Retrieve ranked context for *query* from all available modes."""
        max_items = max_items or int(self.config.get("context.max_files", 40))
        items: list[ContextItem] = []

        # Structural: identifiers in the query that name known symbols.
        seen_symbols: set[str] = set()
        for token in set(_IDENT_RE.findall(query)):
            for sym in self.index.find_symbols(token):
                key = f"{sym['file_path']}:{sym['line_start']}"
                if key in seen_symbols:
                    continue
                seen_symbols.add(key)
                items.append(ContextItem(
                    path=sym["file_path"],
                    line_start=sym["line_start"],
                    line_end=sym["line_end"] or sym["line_start"],
                    kind=sym["kind"],
                    symbol=sym["name"],
                    relevance=0.9,
                    reason=f"symbol '{sym['name']}' ({sym['kind']}) matches query token",
                    text=self._read_span(sym["file_path"], sym["line_start"],
                                         sym["line_end"] or sym["line_start"]),
                ))

        # Semantic: similar chunks (best-effort; empty if not built/available).
        try:
            for hit in self.search_semantic(query):
                key = f"{hit.path}:{hit.start}"
                if key in seen_symbols:
                    continue
                items.append(ContextItem(
                    path=hit.path, line_start=hit.start, line_end=hit.end,
                    kind="chunk", symbol=None, relevance=round(hit.score, 4),
                    reason=f"semantic similarity {hit.score:.2f}",
                    text=hit.text,
                ))
        except CleError:
            pass  # embedding model/daemon unavailable — degrade to structural only

        items.sort(key=lambda it: it.relevance, reverse=True)
        return items[:max_items]

    # -- helpers ------------------------------------------------------------

    def _read_span(self, rel_path: str, start: int, end: int, pad: int = 2) -> str:
        try:
            text = (self.root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
        lines = text.splitlines()
        lo = max(0, start - 1 - pad)
        hi = min(len(lines), end + pad)
        return "\n".join(lines[lo:hi])
