"""Runtime context assembly.

Builds the object graph a command needs — config, project, provider, registry,
router, audit log — from the current working directory. Commands receive an
:class:`AppContext` and stay free of wiring concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config, load_config
from .logging_setup import setup_logging
from .models.base import ModelProvider
from .models.ollama import OllamaProvider
from .models.orchestrator import Orchestrator
from .models.registry import ModelRegistry
from .models.router import ModelRouter
from .project import Project, detect_project
from .safety.audit import AuditLog


@dataclass
class AppContext:
    config: Config
    project: Project
    provider: ModelProvider
    registry: ModelRegistry
    router: ModelRouter
    audit: AuditLog
    orchestrator: Orchestrator


def _build_provider(config: Config) -> ModelProvider:
    provider_type = config.get("provider.type", "ollama")
    if provider_type == "ollama":
        num_ctx = config.get("provider.num_ctx", None)
        return OllamaProvider(
            host=config.get("provider.host", "http://127.0.0.1:11434"),
            timeout_seconds=float(config.get("provider.timeout_seconds", 300)),
            connect_timeout_seconds=float(
                config.get("provider.connect_timeout_seconds", 5)
            ),
            num_ctx=int(num_ctx) if num_ctx else None,
        )
    # Only Ollama exists today; future providers slot in here behind the same
    # interface without touching callers.
    raise ValueError(f"Unknown provider type: {provider_type!r}")


def build_context(
    start: Path | None = None,
    *,
    verbose: bool = False,
) -> AppContext:
    """Assemble an :class:`AppContext` rooted at *start* (defaults to cwd)."""
    project = detect_project(start)
    root = project.root if project.is_initialized else None
    config = load_config(root)

    level = "DEBUG" if verbose else str(config.get("logging.level", "INFO"))
    setup_logging(level)

    registry = ModelRegistry(config)
    router = ModelRouter(config, registry)
    provider = _build_provider(config)
    orchestrator = Orchestrator(provider, router, registry, config)

    audit = AuditLog(
        logs_root=project.root / "logs",
        project=str(project.root),
        enabled=bool(config.get("logging.audit", True)),
    )
    return AppContext(
        config=config,
        project=project,
        provider=provider,
        registry=registry,
        router=router,
        audit=audit,
        orchestrator=orchestrator,
    )
