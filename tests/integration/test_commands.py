"""Command-level tests with a fake provider (offline)."""

from __future__ import annotations

from cle.cli import commands
from cle.config import load_config
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


def test_cmd_ask_routes_to_fast_model(project_dir):
    provider = FakeProvider()
    ctx = make_context(project_dir, provider=provider, models={"fast": "fastmodel"})
    code = commands.cmd_ask(ctx, "what is 2+2?")
    assert code == 0
    assert provider.calls == [("generate", "fastmodel")]


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
