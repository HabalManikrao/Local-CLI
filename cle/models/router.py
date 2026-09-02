"""Model router.

Maps a task *intent* to a role (via configurable ``routing`` in config) and
then to a concrete model (via the registry). Keeping intent→role→model in
config means models can change without code changes.

Milestone 1 provides intent routing; Milestone 3 adds health-aware selection
and fallbacks.
"""

from __future__ import annotations

from ..config import Config
from .registry import ModelRegistry

# Known intents map to roles through config (routing.<intent>).
DEFAULT_INTENT = "default"


class ModelRouter:
    def __init__(self, config: Config, registry: ModelRegistry):
        self._config = config
        self._registry = registry

    def role_for_intent(self, intent: str) -> str:
        """Return the configured role for *intent*, falling back to default."""
        role = self._config.get(f"routing.{intent}")
        if not role:
            role = self._config.get(f"routing.{DEFAULT_INTENT}", "fast")
        return role

    def model_for_intent(self, intent: str) -> str:
        """Resolve *intent* all the way to a concrete model name.

        Raises :class:`ModelNotConfiguredError` if the chosen role is unset.
        """
        role = self.role_for_intent(intent)
        return self._registry.resolve(role)
