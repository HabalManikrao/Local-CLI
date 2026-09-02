"""End-to-end CLI tests via Typer's CliRunner.

These exercise the real app wiring (arg parsing, context build, output) but do
not require a running Ollama daemon: init/status/version don't touch the
provider, and doctor tolerates a down daemon.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cle.cli.main import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cle" in result.stdout


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    # no_args_is_help exits non-zero (2) but prints usage.
    assert "Usage" in result.stdout or "Commands" in result.stdout


def test_init_then_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r_init = runner.invoke(app, ["init"])
    assert r_init.exit_code == 0
    assert (tmp_path / ".cle" / "config.yaml").exists()

    r_status = runner.invoke(app, ["status"])
    assert r_status.exit_code == 0
    assert "Initialized" in r_status.stdout


def test_model_use_via_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    r = runner.invoke(app, ["model", "use", "coding", "codellama"])
    assert r.exit_code == 0
    r2 = runner.invoke(app, ["status"])
    assert "codellama" in r2.stdout


def test_doctor_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    # Exit code depends on environment (daemon may be down); just ensure it ran
    # and produced the diagnostics table.
    assert "cle doctor" in result.stdout
    assert "Python" in result.stdout
