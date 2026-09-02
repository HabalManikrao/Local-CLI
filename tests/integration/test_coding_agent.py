"""Coding agent: JSON extraction, plan (no writes), and guarded apply."""

from __future__ import annotations

import json

import pytest

from cle.agents.base import AgentError, extract_json
from cle.agents.coding import CodingAgent
from cle.cli import commands
from cle.config import load_config
from cle.models.registry import ModelRegistry
from cle.models.router import ModelRouter
from cle.safety.permissions import PermissionGuard, PermissionPolicy, approve_all
from cle.tools.filesystem import FileSystem

from tests.conftest import FakeProvider, make_context


# -- extract_json -----------------------------------------------------------

def test_extract_json_fenced():
    text = "Sure!\n```json\n{\"a\": 1}\n```\nDone."
    assert extract_json(text) == {"a": 1}


def test_extract_json_embedded():
    text = 'prefix {"goal": "x", "changes": []} suffix'
    assert extract_json(text)["goal"] == "x"


def test_extract_json_failure():
    with pytest.raises(AgentError):
        extract_json("no json here")


# -- scripted provider ------------------------------------------------------

class PlanProvider(FakeProvider):
    """Returns a fixed coding plan as JSON from generate()."""

    def __init__(self, plan: dict):
        super().__init__()
        self._plan = plan

    def generate(self, model, prompt, *, system=None):
        from cle.models.base import GenerateResult
        return GenerateResult(text="```json\n" + json.dumps(self._plan) + "\n```", model=model)


def _agent(root, plan):
    from cle.config import set_project_value
    set_project_value(root, "models.coding", "coder")
    cfg = load_config(root)
    reg = ModelRegistry(cfg)
    router = ModelRouter(cfg, reg)
    provider = PlanProvider(plan)
    return CodingAgent(root, provider, router, reg, cfg)


PLAN = {
    "goal": "add greeting",
    "reasoning": "create a new module",
    "expected_impact": "adds hello.py",
    "risks": ["none"],
    "tests_to_run": ["pytest"],
    "changes": [
        {"op": "CREATE_FILE", "path": "hello.py", "content": "print('hi')\n",
         "explanation": "new file"},
    ],
}


@pytest.mark.integration
def test_plan_makes_no_writes(tmp_path):
    (tmp_path / ".cle").mkdir()
    agent = _agent(tmp_path, PLAN)
    plan = agent.plan("add a greeting module")
    assert plan.goal == "add greeting"
    assert plan.validation_errors == []
    assert len(plan.edit_plan.ops) == 1
    # Crucially: nothing written during planning.
    assert not (tmp_path / "hello.py").exists()


@pytest.mark.integration
def test_apply_writes_after_approval(tmp_path):
    (tmp_path / ".cle").mkdir()
    agent = _agent(tmp_path, PLAN)
    plan = agent.plan("add a greeting module")
    guard = PermissionGuard(PermissionPolicy(require_approval=False), approver=approve_all)
    fs = FileSystem(tmp_path, guard)
    results = agent.apply(plan, fs)
    assert (tmp_path / "hello.py").read_text() == "print('hi')\n"
    assert results == ["wrote hello.py"]


@pytest.mark.integration
def test_apply_refuses_invalid_plan(tmp_path):
    (tmp_path / ".cle").mkdir()
    bad = {"goal": "x", "changes": [
        {"op": "MODIFY_FILE", "path": "missing.py", "content": "x"}]}
    agent = _agent(tmp_path, bad)
    plan = agent.plan("edit missing")
    assert plan.validation_errors  # file does not exist
    guard = PermissionGuard(PermissionPolicy(require_approval=False), approver=approve_all)
    with pytest.raises(AgentError):
        agent.apply(plan, FileSystem(tmp_path, guard))


@pytest.mark.integration
def test_cmd_code_no_apply_does_not_write(tmp_path, capsys):
    ctx = make_context(tmp_path, provider=PlanProvider(PLAN), models={"coding": "c"})
    code = commands.cmd_code(ctx, "add greeting", yes=False, no_apply=True)
    assert code == 0
    assert not (tmp_path / "hello.py").exists()
    assert "Goal" in capsys.readouterr().out


@pytest.mark.integration
def test_cmd_code_applies_with_yes(tmp_path, capsys):
    ctx = make_context(tmp_path, provider=PlanProvider(PLAN), models={"coding": "c"})
    code = commands.cmd_code(ctx, "add greeting", yes=True, no_apply=False)
    assert code == 0
    assert (tmp_path / "hello.py").read_text() == "print('hi')\n"
