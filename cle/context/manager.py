"""Context assembly.

Formats retrieved :class:`ContextItem`s into a bounded prompt block for the
model, enforcing an approximate token budget (chars ≈ tokens × 4) and keeping
every snippet's provenance visible so answers can cite sources.
"""

from __future__ import annotations

from ..config import Config
from .retrieval import ContextItem

_CHARS_PER_TOKEN = 4


class ContextManager:
    def __init__(self, config: Config):
        self.max_chars = int(config.get("context.max_tokens", 8000)) * _CHARS_PER_TOKEN

    def build_block(self, items: list[ContextItem]) -> tuple[str, list[ContextItem]]:
        """Return (formatted context block, items that fit the budget)."""
        parts: list[str] = []
        used = 0
        included: list[ContextItem] = []
        for item in items:
            header = f"### {item.location()}"
            if item.symbol:
                header += f"  [{item.kind} {item.symbol}]"
            header += f"  (source={item.source.value}, reason={item.reason})"
            snippet = f"{header}\n```\n{item.text}\n```\n"
            if used + len(snippet) > self.max_chars and included:
                break
            parts.append(snippet)
            used += len(snippet)
            included.append(item)
        return "\n".join(parts), included
