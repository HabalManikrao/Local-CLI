"""Model registry.

Maps task *roles* (fast / coding / reasoning / embedding) to concrete model
names drawn from config. No model names are hard-coded (master prompt §20):
roles are resolved at runtime, and an unset role produces a structured,
actionable error rather than a crash.

Milestone 3 extends this with health checks; Milestone 1 provides resolution.
"""

from __future__ import annotations

from ..config import Config
from ..errors import ModelNotConfiguredError

# Canonical roles recognised by the system.
ROLES = ("fast", "coding", "reasoning", "embedding")


class ModelRegistry:
    def __init__(self, config: Config):
        self._config = config

    def configured(self) -> dict[str, str]:
        """Return {role: model} for every role that has a non-empty model."""
        out: dict[str, str] = {}
        for role in ROLES:
            name = self._config.get(f"models.{role}", "") or ""
            if name:
                out[role] = name
        return out

    def all_roles(self) -> dict[str, str]:
        """Return {role: model_or_empty_string} for every known role."""
        return {role: (self._config.get(f"models.{role}", "") or "") for role in ROLES}

    def resolve(self, role: str) -> str:
        """Return the model name for *role*, or raise if unset/unknown."""
        if role not in ROLES:
            raise ModelNotConfiguredError(
                f"Unknown model role '{role}'. Known roles: {', '.join(ROLES)}."
            )
        name = self._config.get(f"models.{role}", "") or ""
        if not name:
            raise ModelNotConfiguredError(
                f"No model configured for role '{role}'.",
                remedy=(
                    f"Assign one after pulling it with Ollama:\n"
                    f"  ollama pull <model>\n"
                    f"  cle model use {role} <model>"
                ),
            )
        return name
