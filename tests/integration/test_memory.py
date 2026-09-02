"""Project memory tests (SQLite-backed, project-scoped)."""

from __future__ import annotations

import pytest

from cle.cli import commands
from cle.memory import decisions
from cle.memory.project import DECISION, ISSUE, ProjectMemory
from cle.memory.session import SessionMemory

from tests.conftest import make_context


@pytest.mark.integration
def test_add_and_list_entries(tmp_path):
    mem = ProjectMemory(tmp_path)
    try:
        mem.record_decision("Use SQLite", "Simple, local, no server")
        mem.record_issue("Flaky login test", "Fails ~1/10 runs")
        assert {e.kind for e in mem.entries()} == {DECISION, ISSUE}
        assert mem.summary() == {DECISION: 1, ISSUE: 1}
    finally:
        mem.close()


@pytest.mark.integration
def test_settings_roundtrip(tmp_path):
    mem = ProjectMemory(tmp_path)
    try:
        mem.set_build_command("mvn -q compile")
        mem.set_test_command("mvn -q test")
        assert mem.get_setting("build_command") == "mvn -q compile"
        assert mem.settings()["test_command"] == "mvn -q test"
        # upsert
        mem.set_build_command("gradle build")
        assert mem.get_setting("build_command") == "gradle build"
    finally:
        mem.close()


@pytest.mark.integration
def test_remove_and_clear(tmp_path):
    mem = ProjectMemory(tmp_path)
    try:
        eid = mem.add_convention("Two-space indent")
        assert mem.remove(eid) is True
        assert mem.remove(9999) is False
        mem.record_decision("keep")
        mem.set_test_command("pytest")
        mem.clear()
        assert mem.entries() == []
        assert mem.settings() == {}
    finally:
        mem.close()


@pytest.mark.integration
def test_project_scoped_isolation(tmp_path):
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()
    ma, mb = ProjectMemory(a), ProjectMemory(b)
    try:
        ma.record_decision("A only")
        assert [e.title for e in ma.entries()] == ["A only"]
        assert mb.entries() == []  # unrelated project sees nothing
    finally:
        ma.close()
        mb.close()


@pytest.mark.integration
def test_decisions_helper(tmp_path):
    mem = ProjectMemory(tmp_path)
    try:
        decisions.record(mem, "Adopt tree-sitter later", "Heuristic parser first")
        ds = decisions.list_decisions(mem)
        assert ds[0].title == "Adopt tree-sitter later"
        assert ds[0].rationale == "Heuristic parser first"
    finally:
        mem.close()


@pytest.mark.integration
def test_session_memory(tmp_path):
    sm = SessionMemory(tmp_path)
    try:
        sid = sm.start("first session")
        sm.add_turn(sid, "user", "hi")
        sm.add_turn(sid, "assistant", "hello")
        turns = sm.turns(sid)
        assert [t["role"] for t in turns] == ["user", "assistant"]
        assert sm.recent_sessions()[0]["label"] == "first session"
    finally:
        sm.db.close()


@pytest.mark.integration
def test_memory_commands(tmp_path, capsys):
    ctx = make_context(tmp_path)
    assert commands.cmd_memory_add(ctx, "decision", "Use roles", "no hardcoded models") == 0
    assert commands.cmd_memory_add(ctx, "bogus", "x", None) == 1
    assert commands.cmd_memory_set(ctx, "test_command", "pytest") == 0
    assert commands.cmd_memory_show(ctx, None) == 0
    out = capsys.readouterr().out
    assert "Use roles" in out and "pytest" in out
    assert commands.cmd_memory_clear(ctx, yes=True) == 0
