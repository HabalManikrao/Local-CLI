"""OllamaProvider tests using httpx.MockTransport — no daemon required."""

from __future__ import annotations

import json

import httpx
import pytest

from cle.errors import ModelNotFoundError, ProviderConnectionError, ProviderError
from cle.models.base import Message
from cle.models.ollama import OllamaProvider


def _provider(handler) -> OllamaProvider:
    return OllamaProvider(transport=httpx.MockTransport(handler))


def test_health_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": []})

    h = _provider(handler).health()
    assert h.ok is True


def test_health_connection_refused():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    h = _provider(handler).health()
    assert h.ok is False
    assert "refused" in h.detail.lower() or "connection" in h.detail.lower()


def test_list_models_parses_details():
    def handler(request):
        return httpx.Response(200, json={
            "models": [
                {"name": "a:latest", "size": 123,
                 "details": {"family": "llama", "parameter_size": "7B"}},
            ]
        })

    models = _provider(handler).list_models()
    assert models[0].name == "a:latest"
    assert models[0].family == "llama"
    assert models[0].parameter_size == "7B"


def test_list_models_connection_error_is_structured():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderConnectionError) as exc:
        _provider(handler).list_models()
    assert "ollama serve" in (exc.value.remedy or "")


def test_generate_returns_text():
    def handler(request):
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body["stream"] is False
        # Default provider sends no options → Ollama keeps its own default.
        assert "options" not in body
        return httpx.Response(200, json={"response": "hello", "eval_count": 5})

    res = _provider(handler).generate("m", "hi")
    assert res.text == "hello"
    assert res.metrics["eval_count"] == 5.0


def test_num_ctx_is_sent_as_option_when_configured():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    provider = OllamaProvider(num_ctx=8192, transport=httpx.MockTransport(handler))
    provider.generate("m", "a big prompt")
    # Without this, Ollama silently truncates long prompts at its 2048 default.
    assert seen["body"]["options"] == {"num_ctx": 8192}

    # chat carries the same window.
    provider.chat("m", [Message("user", "hi")])
    assert seen["body"]["options"] == {"num_ctx": 8192}


def test_chat_returns_message_content():
    def handler(request):
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": "yo"}})

    res = _provider(handler).chat("m", [Message("user", "hi")])
    assert res.text == "yo"


def test_model_not_found_is_translated():
    def handler(request):
        return httpx.Response(404, text="model 'x' not found")

    with pytest.raises(ModelNotFoundError) as exc:
        _provider(handler).generate("x", "hi")
    assert "ollama pull x" in (exc.value.remedy or "")


def test_stream_yields_chunks_until_done():
    lines = [
        json.dumps({"message": {"content": "he"}, "done": False}),
        json.dumps({"message": {"content": "llo"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]

    def handler(request):
        return httpx.Response(200, text="\n".join(lines))

    chunks = list(_provider(handler).stream("m", [Message("user", "hi")]))
    assert "".join(chunks) == "hello"


def test_stream_skips_non_json_lines():
    # A real daemon can interleave a non-JSON notice line; it must not crash.
    lines = [
        json.dumps({"message": {"content": "he"}, "done": False}),
        "this is not json",
        json.dumps({"message": {"content": "llo"}, "done": True}),
    ]

    def handler(request):
        return httpx.Response(200, text="\n".join(lines))

    chunks = list(_provider(handler).stream("m", [Message("user", "hi")]))
    assert "".join(chunks) == "hello"      # bad line skipped, not fatal


def test_stream_http_error_is_structured_not_responsenotread():
    # Streaming HTTP >=400 must surface as a ProviderError, not ResponseNotRead.
    def handler(request):
        return httpx.Response(500, text="model failed to load")

    with pytest.raises(ProviderError):
        list(_provider(handler).stream("m", [Message("user", "hi")]))


def test_embed_returns_vector():
    def handler(request):
        assert request.url.path == "/api/embeddings"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    vec = _provider(handler).embed("m", "text")
    assert vec == [0.1, 0.2, 0.3]


def test_embed_missing_vector_raises():
    def handler(request):
        return httpx.Response(200, json={})

    with pytest.raises(ProviderError):
        _provider(handler).embed("m", "text")


def test_generate_forwards_system_prompt():
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={"response": "ok"})

    _provider(handler).generate("m", "hi", system="be terse")
    assert seen["system"] == "be terse"


def test_timeout_is_translated_to_provider_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as exc:
        _provider(handler).generate("m", "hi")
    assert "timed out" in exc.value.message.lower()


def test_host_trailing_slash_is_normalized():
    p = OllamaProvider(host="http://example:1234/")
    assert p.host == "http://example:1234"
