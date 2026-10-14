"""Retrieval engine + M5 command tests (offline)."""

from __future__ import annotations

import pytest

from cle.cli import commands
from cle.context.retrieval import ContextEngine
from cle.indexing.repository import RepositoryIndex
from tests.conftest import make_context


def _seed_java(root):
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "LoginPage.java").write_text(
        "package app;\n"
        "public class LoginPage {\n"
        "  private WiniumDriver driver;\n"
        "  public void login() {}\n"
        "}\n",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_retrieve_structural(tmp_path):
    _seed_java(tmp_path)
    ctx = make_context(tmp_path)
    index = RepositoryIndex(tmp_path)
    try:
        index.rebuild()
        engine = ContextEngine(tmp_path, index, ctx.provider, ctx.registry, ctx.config)
        items = engine.retrieve("where is login defined")
        assert any(it.symbol == "login" for it in items)
        item = next(it for it in items if it.symbol == "login")
        assert item.source.value == "LOCAL"
        assert "login" in item.reason
    finally:
        index.close()


@pytest.mark.integration
def test_cmd_symbol_requires_index(tmp_path, capsys):
    ctx = make_context(tmp_path)
    code = commands.cmd_symbol(ctx, "LoginPage")
    assert code == 1
    captured = capsys.readouterr()
    assert "not indexed" in (captured.out + captured.err).lower()


@pytest.mark.integration
def test_cmd_symbol_finds_after_index(tmp_path, capsys):
    _seed_java(tmp_path)
    ctx = make_context(tmp_path)
    index = RepositoryIndex(tmp_path)
    index.rebuild()
    index.close()
    code = commands.cmd_symbol(ctx, "LoginPage")
    assert code == 0
    assert "LoginPage" in capsys.readouterr().out


@pytest.mark.integration
def test_cmd_search(tmp_path, capsys):
    _seed_java(tmp_path)
    ctx = make_context(tmp_path)
    code = commands.cmd_search(ctx, "WiniumDriver", ignore_case=False, fixed=False)
    assert code == 0
    assert "LoginPage.java" in capsys.readouterr().out


@pytest.mark.integration
def test_cmd_explain_uses_reasoning_model(tmp_path, capsys):
    _seed_java(tmp_path)
    ctx = make_context(tmp_path, models={"reasoning": "reasoner"})
    index = RepositoryIndex(tmp_path)
    index.rebuild()
    index.close()
    code = commands.cmd_explain(ctx, "src/LoginPage.java")
    assert code == 0
    # FakeProvider echoes "[model] prompt"; confirm reasoning model was used.
    assert "[reasoner]" in capsys.readouterr().out


@pytest.mark.integration
def test_cmd_explain_missing_file(tmp_path):
    ctx = make_context(tmp_path, models={"reasoning": "reasoner"})
    assert commands.cmd_explain(ctx, "nope.java") == 1
