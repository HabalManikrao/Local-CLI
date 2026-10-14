"""End-to-end autopilot: plan → edit → test → self-repair → report."""

from __future__ import annotations

import json

import pytest

from cle.cli import commands
from cle.models.base import GenerateResult
from tests.conftest import FakeProvider, make_context


def _project(root):
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    (root / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
        encoding="utf-8",
    )


class RepairProvider(FakeProvider):
    """First plan creates a buggy module; the next plan fixes it."""

    def __init__(self):
        super().__init__()
        self.n = 0

    def generate(self, model, prompt, *, system=None):
        self.n += 1
        if self.n == 1:
            plan = {"goal": "create calc", "changes": [
                {"op": "CREATE_FILE", "path": "calc.py",
                 "content": "def add(a, b):\n    return a - b\n", "explanation": "buggy"}]}
        else:
            plan = {"goal": "fix calc", "changes": [
                {"op": "MODIFY_FILE", "path": "calc.py",
                 "content": "def add(a, b):\n    return a + b\n", "explanation": "fix"}]}
        return GenerateResult(text=json.dumps(plan), model=model)


@pytest.mark.e2e
def test_autopilot_self_repairs(tmp_path):
    _project(tmp_path)
    ctx = make_context(tmp_path, provider=RepairProvider(), models={"coding": "c"})
    code = commands.cmd_autopilot(ctx, "implement add()", max_iterations=3, yes=True)
    assert code == 0
    assert "a + b" in (tmp_path / "calc.py").read_text()


@pytest.mark.e2e
def test_autopilot_bounded_when_unfixable(tmp_path):
    _project(tmp_path)

    class AlwaysBuggy(FakeProvider):
        def generate(self, model, prompt, *, system=None):
            plan = {"goal": "x", "changes": [
                {"op": "CREATE_FILE" if not (tmp_path / "calc.py").exists() else "MODIFY_FILE",
                 "path": "calc.py",
                 "content": "def add(a, b):\n    return a - b\n", "explanation": "still buggy"}]}
            return GenerateResult(text=json.dumps(plan), model=model)

    ctx = make_context(tmp_path, provider=AlwaysBuggy(), models={"coding": "c"})
    code = commands.cmd_autopilot(ctx, "implement add()", max_iterations=2, yes=True)
    assert code == 1  # never passes → bounded failure, not an infinite loop
