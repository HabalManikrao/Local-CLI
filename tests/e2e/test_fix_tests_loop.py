"""End-to-end test/debug/fix-tests loop against a real pytest project."""

from __future__ import annotations

import json

import pytest

from cle.cli import commands

from tests.conftest import FakeProvider, make_context


def _make_pytest_project(root):
    # Minimal detectable python project with a failing test.
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
        encoding="utf-8",
    )


class FixProvider(FakeProvider):
    """Returns a coding plan that fixes calc.add."""

    def generate(self, model, prompt, *, system=None):
        from cle.models.base import GenerateResult
        plan = {
            "goal": "fix add()",
            "reasoning": "use + not -",
            "changes": [
                {"op": "MODIFY_FILE", "path": "calc.py",
                 "content": "def add(a, b):\n    return a + b\n",
                 "explanation": "correct operator"},
            ],
        }
        return GenerateResult(text=json.dumps(plan), model=model)


@pytest.mark.e2e
def test_cmd_test_detects_failure(tmp_path):
    _make_pytest_project(tmp_path)
    ctx = make_context(tmp_path)
    assert commands.cmd_test(ctx) == 1  # failing test → exit 1


@pytest.mark.e2e
def test_fix_tests_repairs_and_passes(tmp_path):
    _make_pytest_project(tmp_path)
    ctx = make_context(tmp_path, provider=FixProvider(), models={"coding": "c"})
    code = commands.cmd_fix_tests(ctx, max_iterations=3, yes=True)
    assert code == 0
    # The source was actually fixed.
    assert "a + b" in (tmp_path / "calc.py").read_text()


@pytest.mark.e2e
def test_fix_tests_bounded_when_no_fix(tmp_path):
    _make_pytest_project(tmp_path)

    class NoFix(FakeProvider):
        def generate(self, model, prompt, *, system=None):
            from cle.models.base import GenerateResult
            return GenerateResult(text='{"goal":"x","changes":[]}', model=model)

    ctx = make_context(tmp_path, provider=NoFix(), models={"coding": "c"})
    code = commands.cmd_fix_tests(ctx, max_iterations=3, yes=True)
    assert code == 1  # no fix proposed → stops, does not loop forever
