"""Shared test fixtures and a deterministic fake model provider.

The fake provider lets every test run fully offline — no Ollama daemon required
(audit §11 / testing strategy). It records calls so tests can assert routing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cle.config import Config, init_project_config, load_config, set_project_value
from cle.models.base import (
    GenerateResult,
    Health,
    Message,
    ModelInfo,
    ModelProvider,
)
from cle.models.registry import ModelRegistry
from cle.models.router import ModelRouter
from cle.project import detect_project
from cle.runtime import AppContext
from cle.safety.audit import AuditLog


class FakeProvider(ModelProvider):
    """In-memory provider with scripted responses and call recording."""

    def __init__(self, healthy: bool = True, installed: list[ModelInfo] | None = None):
        self.healthy = healthy
        self.installed = installed if installed is not None else [
            ModelInfo(name="demo:latest", size_bytes=2_000_000_000, parameter_size="3B")
        ]
        self.calls: list[tuple[str, str]] = []  # (method, model)

    def health(self) -> Health:
        return Health(
            ok=self.healthy,
            detail="reachable" if self.healthy else "connection refused",
            host="http://fake",
        )

    def list_models(self) -> list[ModelInfo]:
        self.calls.append(("list_models", ""))
        return list(self.installed)

    def generate(self, model, prompt, *, system=None) -> GenerateResult:
        self.calls.append(("generate", model))
        return GenerateResult(text=f"[{model}] {prompt}", model=model)

    def chat(self, model, messages: list[Message]) -> GenerateResult:
        self.calls.append(("chat", model))
        last = messages[-1].content if messages else ""
        return GenerateResult(text=f"[{model}] {last}", model=model)

    def stream(self, model, messages: list[Message]) -> Iterator[str]:
        self.calls.append(("stream", model))
        for word in (messages[-1].content if messages else "").split():
            yield word + " "

    def embed(self, model, text) -> list[float]:
        self.calls.append(("embed", model))
        return [float(len(text)), 0.0, 1.0]


def make_context(
    root: Path,
    *,
    provider: ModelProvider | None = None,
    models: dict[str, str] | None = None,
    initialized: bool = True,
) -> AppContext:
    """Assemble an AppContext rooted at *root* with an optional fake provider."""
    if initialized:
        init_project_config(root)
        for role, name in (models or {}).items():
            set_project_value(root, f"models.{role}", name)
    config: Config = load_config(root if initialized else None)
    project = detect_project(root)
    registry = ModelRegistry(config)
    router = ModelRouter(config, registry)
    prov = provider or FakeProvider()
    audit = AuditLog(logs_root=root / "logs", project=str(root), enabled=False)
    return AppContext(
        config=config,
        project=project,
        provider=prov,
        registry=registry,
        router=router,
        audit=audit,
    )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A temporary directory usable as a project root."""
    return tmp_path


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()
