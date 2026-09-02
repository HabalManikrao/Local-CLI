"""Structured, actionable errors.

Every error carries a human message and, where possible, a `remedy` — a
concrete next step the user can take. This is the mechanism behind the
"Good vs Bad" error requirement (master prompt §12): never surface a bare
"something went wrong".
"""

from __future__ import annotations


class CleError(Exception):
    """Base class for all CLE errors.

    Parameters
    ----------
    message:
        What went wrong, in plain language.
    remedy:
        An optional concrete next step (often a shell command) the user can
        run to resolve the problem.
    """

    def __init__(self, message: str, remedy: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def render(self) -> str:
        """Return a multi-line, user-facing rendering of the error."""
        out = self.message
        if self.remedy:
            out += f"\n\nTry:\n{self.remedy}"
        return out


class ConfigError(CleError):
    """Configuration is missing, malformed, or inconsistent."""


class ProjectError(CleError):
    """No project context, or the project is in an unusable state."""


class ProviderError(CleError):
    """The model provider (e.g. Ollama) could not be reached or failed."""


class ProviderConnectionError(ProviderError):
    """The provider host refused the connection or timed out connecting."""


class ModelNotFoundError(ProviderError):
    """A requested model is not available on the provider."""


class ModelNotConfiguredError(CleError):
    """A task role has no model assigned in config."""


class PermissionDeniedError(CleError):
    """A tool action was blocked by the permission/safety layer."""


class GitError(CleError):
    """A git operation failed or the repo is in an unexpected state."""
