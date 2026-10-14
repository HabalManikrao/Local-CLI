"""DebugAgent.diagnose and the cle debug command glue (previously 0% covered)."""

from __future__ import annotations

import pytest

from cle.agents.debugging import DebugAgent
from cle.cli import commands
from cle.config import load_config, set_project_value
from cle.models.registry import ModelRegistry
from cle.models.router import ModelRouter
from cle.tools.test_runner import BuildSystem, TestFailure, TestRunResult
from tests.conftest import FakeProvider, make_context


def _debug_agent(root):
    set_project_value(root, "models.reasoning", "reason")
    cfg = load_config(root)
    reg = ModelRegistry(cfg)
    router = ModelRouter(cfg, reg)
    return DebugAgent(root, FakeProvider(), router, reg, cfg)


def _failing_result() -> TestRunResult:
    return TestRunResult(
        system=BuildSystem.PYTHON,
        command=["pytest"],
        returncode=1,
        passed=False,
        output="E   assert 1 == 2\n",
        failures=[TestFailure(name="t::test_x", file="t.py", line=12,
                              message="assert 1 == 2")],
    )


@pytest.mark.integration
def test_diagnose_routes_to_reasoning_and_includes_failures(tmp_path):
    (tmp_path / ".cle").mkdir()
    agent = _debug_agent(tmp_path)
    diagnosis = agent.diagnose(_failing_result())
    # FakeProvider echoes "[model] prompt"; prove routing + that the failing
    # test and the raw-output tail made it into the prompt.
    assert "[reason]" in diagnosis           # routed to the reasoning role
    assert "test_x" in diagnosis and "t.py:12" in diagnosis
    assert "assert 1 == 2" in diagnosis


@pytest.mark.integration
def test_diagnose_handles_no_structured_failures(tmp_path):
    (tmp_path / ".cle").mkdir()
    agent = _debug_agent(tmp_path)
    result = TestRunResult(
        system=BuildSystem.PYTHON, command=["pytest"], returncode=1,
        passed=False, output="boom\n", failures=[],
    )
    diagnosis = agent.diagnose(result)
    assert "no structured failures" in diagnosis


@pytest.mark.integration
def test_cmd_debug_reports_unrunnable_tests(tmp_path, capsys):
    # No build system in an empty project → structured error, exit 1 (covers the
    # command's error branch without needing a real failing test suite).
    ctx = make_context(tmp_path, models={"reasoning": "reason"})
    code = commands.cmd_debug(ctx)
    assert code == 1
