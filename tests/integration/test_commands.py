"""Command-level tests with a fake provider (offline)."""

from __future__ import annotations

from cle.cli import commands, ui
from cle.config import load_config
from cle.errors import ProviderError
from tests.conftest import FakeProvider, make_context


def test_cmd_init_creates_config(project_dir):
    ctx = make_context(project_dir, initialized=False)
    code = commands.cmd_init(ctx)
    assert code == 0
    assert (project_dir / ".cle" / "config.yaml").exists()


def test_cmd_model_use_persists(project_dir):
    ctx = make_context(project_dir)
    code = commands.cmd_model_use(ctx, "coding", "codellama:13b")
    assert code == 0
    cfg = load_config(project_dir)
    assert cfg.get("models.coding") == "codellama:13b"


def test_cmd_model_use_rejects_bad_role(project_dir):
    ctx = make_context(project_dir)
    assert commands.cmd_model_use(ctx, "wizard", "x") == 1


def test_cmd_ask_streams_from_fast_model(project_dir, capsys):
    provider = FakeProvider()
    ctx = make_context(project_dir, provider=provider, models={"fast": "fastmodel"})
    code = commands.cmd_ask(ctx, "what is 2+2?")
    assert code == 0
    # ask now streams (token-by-token) via the fast model, not a one-shot generate.
    assert provider.calls == [("stream", "fastmodel")]
    # FakeProvider.stream echoes the question's words as they "arrive".
    out = capsys.readouterr().out
    assert "what" in out and "2+2?" in out


# -- cle chat (interactive streaming REPL) ----------------------------------

def _scripted_input(monkeypatch, lines):
    it = iter(lines)
    monkeypatch.setattr(ui.console, "input", lambda *a, **k: next(it))


def test_cmd_chat_streams_then_exits(project_dir, monkeypatch, capsys):
    ctx = make_context(project_dir, provider=FakeProvider(), models={"fast": "f"})
    # Blank line is skipped; "exit" quits. FakeProvider.stream echoes the words.
    _scripted_input(monkeypatch, ["", "hello world", "exit"])
    assert commands.cmd_chat(ctx) == 0
    out = capsys.readouterr().out
    assert "hello" in out and "world" in out
    assert "bye" in out


def test_cmd_chat_exits_on_eof(project_dir, monkeypatch):
    ctx = make_context(project_dir, provider=FakeProvider(), models={"fast": "f"})
    def raise_eof(*a, **k):
        raise EOFError
    monkeypatch.setattr(ui.console, "input", raise_eof)
    assert commands.cmd_chat(ctx) == 0


def test_cmd_chat_recovers_from_stream_error(project_dir, monkeypatch, capsys):
    # A provider error mid-chat prints the error, drops the turn, and the REPL
    # keeps going to the next prompt instead of crashing.
    class FailingProvider(FakeProvider):
        def stream(self, model, messages):
            raise ProviderError("daemon died", remedy="start ollama")

    ctx = make_context(project_dir, provider=FailingProvider(), models={"fast": "f"})
    _scripted_input(monkeypatch, ["hi", "exit"])
    assert commands.cmd_chat(ctx) == 0
    assert "daemon died" in capsys.readouterr().err


def test_cmd_ask_errors_when_role_unset(project_dir, capsys):
    ctx = make_context(project_dir)  # no models configured
    code = commands.cmd_ask(ctx, "hello")
    assert code == 1
    out = capsys.readouterr()
    assert "No model configured" in (out.out + out.err)


def test_cmd_models_lists_installed(project_dir, capsys):
    provider = FakeProvider()
    ctx = make_context(project_dir, provider=provider, models={"fast": "f"})
    assert commands.cmd_models(ctx) == 0
    out = capsys.readouterr().out
    assert "demo:latest" in out


def test_cmd_models_handles_daemon_down(project_dir, capsys):
    class Down(FakeProvider):
        def list_models(self):
            from cle.errors import ProviderConnectionError
            raise ProviderConnectionError("no daemon", remedy="ollama serve")

    ctx = make_context(project_dir, provider=Down())
    assert commands.cmd_models(ctx) == 1


def test_cmd_status_reports_not_indexed(project_dir, capsys):
    ctx = make_context(project_dir, models={"coding": "cc"})
    assert commands.cmd_status(ctx) == 0
    out = capsys.readouterr().out
    assert "not indexed" in out


def test_cmd_doctor_returns_1_when_daemon_down(project_dir):
    ctx = make_context(project_dir, provider=FakeProvider(healthy=False))
    assert commands.cmd_doctor(ctx) == 1


def test_cmd_doctor_ok_when_healthy_and_configured(project_dir):
    ctx = make_context(
        project_dir,
        provider=FakeProvider(healthy=True),
        models={"fast": "f", "coding": "c", "reasoning": "r", "embedding": "e"},
    )
    # Doctor may still WARN (e.g. GPU), but must not FAIL with a healthy daemon.
    assert commands.cmd_doctor(ctx) == 0
