"""Opt-in live smoke test against a real Ollama daemon.

Skipped by default (and in CI) — the rest of the suite is fully offline. Enable
with ``CLE_LIVE_TESTS=1`` when a daemon is running with at least one model; it
still skips gracefully if the daemon is down or no models are installed. This is
the only test that exercises real model I/O (SSE framing, real responses), which
mocks cannot cover.
"""

from __future__ import annotations

import os

import pytest

from cle.models.base import Message
from cle.models.ollama import OllamaProvider

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("CLE_LIVE_TESTS") != "1",
        reason="live Ollama test; set CLE_LIVE_TESTS=1 (needs a daemon + a model)",
    ),
]


def _ready_provider() -> tuple[OllamaProvider, str]:
    prov = OllamaProvider()
    if not prov.health().ok:
        pytest.skip("Ollama daemon not reachable")
    # Exclude embedding-only models (they 400 on generate/chat).
    chat_models = [m for m in prov.list_models() if "embed" not in m.name.lower()]
    if not chat_models:
        pytest.skip("no chat-capable Ollama model installed")
    return prov, chat_models[0].name


def test_live_generate_returns_text():
    prov, model = _ready_provider()
    result = prov.generate(model, "Reply with a single short word.")
    assert result.text.strip()          # a real, non-empty response


def test_live_stream_yields_chunks():
    prov, model = _ready_provider()
    chunks = list(prov.stream(model, [Message("user", "Say hello in one word.")]))
    assert "".join(chunks).strip()       # real SSE framing produced content
