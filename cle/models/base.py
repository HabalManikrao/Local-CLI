"""The model provider interface and shared data types.

This is the single seam every LLM call passes through. Implementations must
translate transport/provider failures into the structured errors in
``cle.errors`` (ProviderConnectionError, ModelNotFoundError, ...), so callers
never see raw HTTP/socket exceptions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    """A single chat message."""

    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ModelInfo:
    """Metadata about a model available on the provider."""

    name: str
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None


@dataclass
class Health:
    """Result of a provider health check."""

    ok: bool
    detail: str
    host: str


@dataclass
class GenerateResult:
    """A non-streaming completion."""

    text: str
    model: str
    # Best-effort provider metrics; absent when the provider does not report them.
    metrics: dict[str, float] = field(default_factory=dict)


class ModelProvider(ABC):
    """Abstract base for all model providers."""

    @abstractmethod
    def health(self) -> Health:
        """Check whether the provider is reachable and responsive."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """List models available on the provider."""

    @abstractmethod
    def generate(self, model: str, prompt: str, *, system: str | None = None) -> GenerateResult:
        """Produce a single completion for *prompt* using *model*."""

    @abstractmethod
    def chat(self, model: str, messages: list[Message]) -> GenerateResult:
        """Produce a chat completion for a message list using *model*."""

    @abstractmethod
    def stream(self, model: str, messages: list[Message]) -> Iterator[str]:
        """Yield chat completion text chunks as they arrive."""

    @abstractmethod
    def embed(self, model: str, text: str) -> list[float]:
        """Return an embedding vector for *text* using *model*."""
