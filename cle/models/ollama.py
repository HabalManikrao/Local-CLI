"""Ollama model provider.

Talks to a local Ollama daemon over HTTP (default ``http://127.0.0.1:11434``).
All transport failures are translated into structured ``cle.errors`` types so
the rest of the system stays provider-agnostic and gives actionable messages.

Milestone 1 implements the full surface (health/list/generate/chat/stream/embed)
with basic timeout and error handling; Milestone 2 hardens edge cases.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from ..errors import (
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
)
from .base import (
    GenerateResult,
    Health,
    Message,
    ModelInfo,
    ModelProvider,
)

_START_OLLAMA_REMEDY = (
    "Start the Ollama daemon, then retry:\n"
    "  ollama serve\n"
    "(or launch the Ollama desktop app)"
)


class OllamaProvider(ModelProvider):
    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
        connect_timeout_seconds: float = 5.0,
        *,
        num_ctx: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self._timeout = httpx.Timeout(
            timeout_seconds, connect=connect_timeout_seconds
        )
        # Ollama defaults num_ctx to 2048 tokens and silently truncates anything
        # longer. Context-heavy commands build far bigger prompts, so we pass an
        # explicit window; None leaves Ollama's default in place.
        self._num_ctx = num_ctx
        # Injectable transport for tests (httpx.MockTransport); None uses the
        # real network transport.
        self._transport = transport

    def _options(self) -> dict[str, Any] | None:
        if self._num_ctx:
            return {"num_ctx": self._num_ctx}
        return None

    # -- internal helpers ---------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.host, timeout=self._timeout, transport=self._transport
        )

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        try:
            with self._client() as client:
                resp = client.post(path, json=payload)
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"Could not connect to Ollama at {self.host}.",
                remedy=_START_OLLAMA_REMEDY,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Ollama request timed out ({path}).",
                remedy="Increase provider.timeout_seconds or try a smaller model.",
            ) from exc
        self._raise_for_status(resp, payload.get("model"))
        return resp

    @staticmethod
    def _raise_for_status(resp: httpx.Response, model: str | None) -> None:
        if resp.status_code == 404 and model:
            raise ModelNotFoundError(
                f"Ollama model '{model}' is unavailable.",
                remedy=(
                    "List installed models:\n  ollama list\n"
                    f"Pull it if needed:\n  ollama pull {model}"
                ),
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:400]}",
            )

    # -- interface ----------------------------------------------------------

    def health(self) -> Health:
        try:
            with self._client() as client:
                resp = client.get("/api/tags")
            resp.raise_for_status()
            return Health(ok=True, detail="Ollama is reachable.", host=self.host)
        except httpx.ConnectError:
            return Health(
                ok=False,
                detail="Connection refused (daemon not running?).",
                host=self.host,
            )
        except httpx.TimeoutException:
            return Health(ok=False, detail="Connection timed out.", host=self.host)
        except httpx.HTTPError as exc:
            return Health(ok=False, detail=str(exc), host=self.host)

    def list_models(self) -> list[ModelInfo]:
        try:
            with self._client() as client:
                resp = client.get("/api/tags")
                resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"Could not connect to Ollama at {self.host}.",
                remedy=_START_OLLAMA_REMEDY,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Failed to list Ollama models: {exc}") from exc

        data = resp.json()
        models: list[ModelInfo] = []
        for item in data.get("models", []):
            details = item.get("details", {}) or {}
            models.append(
                ModelInfo(
                    name=item.get("name", ""),
                    size_bytes=item.get("size"),
                    family=details.get("family"),
                    parameter_size=details.get("parameter_size"),
                )
            )
        return models

    def generate(
        self, model: str, prompt: str, *, system: str | None = None
    ) -> GenerateResult:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if (options := self._options()) is not None:
            payload["options"] = options
        resp = self._post("/api/generate", payload)
        data = resp.json()
        return GenerateResult(
            text=data.get("response", ""),
            model=model,
            metrics=_extract_metrics(data),
        )

    def chat(self, model: str, messages: list[Message]) -> GenerateResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
        }
        if (options := self._options()) is not None:
            payload["options"] = options
        resp = self._post("/api/chat", payload)
        data = resp.json()
        return GenerateResult(
            text=data.get("message", {}).get("content", ""),
            model=model,
            metrics=_extract_metrics(data),
        )

    def stream(self, model: str, messages: list[Message]) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
        }
        if (options := self._options()) is not None:
            payload["options"] = options
        try:
            with (
                self._client() as client,
                client.stream("POST", "/api/chat", json=payload) as resp,
            ):
                # A streamed response is not auto-read; _raise_for_status
                # inspects .text, which would raise ResponseNotRead on a
                # real error body (e.g. HTTP 500 on model OOM).
                if resp.status_code >= 400:
                    resp.read()
                self._raise_for_status(resp, model)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        # The daemon can emit non-JSON notices or a partial
                        # line; skip rather than killing the chat session.
                        continue
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"Could not connect to Ollama at {self.host}.",
                remedy=_START_OLLAMA_REMEDY,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Ollama streaming request timed out.",
                remedy="Increase provider.timeout_seconds or try a smaller model.",
            ) from exc

    def embed(self, model: str, text: str) -> list[float]:
        resp = self._post("/api/embeddings", {"model": model, "prompt": text})
        data = resp.json()
        vector = data.get("embedding")
        if not isinstance(vector, list):
            raise ProviderError(
                "Ollama returned no embedding vector.",
                remedy="Confirm the model supports embeddings (e.g. an embedding model).",
            )
        return [float(x) for x in vector]


def _extract_metrics(data: dict[str, Any]) -> dict[str, float]:
    """Pull best-effort numeric metrics from an Ollama response."""
    keys = (
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    )
    return {k: float(data[k]) for k in keys if isinstance(data.get(k), (int, float))}
