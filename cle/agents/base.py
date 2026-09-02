"""Agent base utilities.

Shared helpers for agents: robust JSON extraction from model output (models
often wrap JSON in prose or ``` fences) and a small base holding the common
dependency graph.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import Config
from ..context.retrieval import ContextEngine
from ..errors import CleError
from ..indexing.repository import RepositoryIndex
from ..models.base import ModelProvider
from ..models.registry import ModelRegistry
from ..models.router import ModelRouter

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AgentError(CleError):
    pass


def extract_json(text: str) -> dict:
    """Best-effort extraction of a single JSON object from model *text*.

    Tries, in order: fenced ```json block, the whole string, and the substring
    between the first '{' and its matching last '}'. Raises AgentError on total
    failure.
    """
    candidates: list[str] = []
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            continue
    raise AgentError(
        "The model did not return valid JSON.",
        remedy="Retry; if it persists, try a stronger 'coding'/'reasoning' model.",
    )


class BaseAgent:
    """Common dependencies for agents."""

    def __init__(
        self,
        root: Path,
        provider: ModelProvider,
        router: ModelRouter,
        registry: ModelRegistry,
        config: Config,
    ):
        self.root = root
        self.provider = provider
        self.router = router
        self.registry = registry
        self.config = config

    def context_engine(self) -> ContextEngine | None:
        """Return a ContextEngine if the project is indexed, else None."""
        index = RepositoryIndex(self.root)
        if not index.is_built():
            index.close()
            return None
        return ContextEngine(
            self.root, index, self.provider, self.registry, self.config
        )
