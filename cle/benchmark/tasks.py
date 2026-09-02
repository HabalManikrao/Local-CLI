"""Built-in benchmark tasks across the required categories:
coding, debugging, refactoring, context retrieval, test fixing, architecture.

Each task builds its own fixture in the provided workdir and reports success.
Model-dependent tasks declare a ``required_role`` and are skipped when unset.
"""

from __future__ import annotations

from pathlib import Path

from ..agents.coding import CodingAgent
from ..agents.debugging import DebugAgent
from ..indexing.repository import RepositoryIndex
from ..safety.permissions import PermissionGuard, PermissionPolicy, approve_all
from ..tools.filesystem import FileSystem
from ..tools.test_runner import run_tests
from .harness import BenchContext, BenchmarkTask

_PYPROJECT = "[tool.pytest.ini_options]\naddopts = '-q'\n"


def _coding_agent(bctx: BenchContext) -> CodingAgent:
    return CodingAgent(bctx.workdir, bctx.provider, bctx.router, bctx.registry, bctx.config)


def _fs(bctx: BenchContext) -> FileSystem:
    guard = PermissionGuard(PermissionPolicy(require_approval=False), approver=approve_all)
    return FileSystem(bctx.workdir, guard)


def _run_pytest(root: Path):
    return run_tests(root)


# -- context retrieval (local, no model) ------------------------------------

def _task_context_retrieval(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / ".cle").mkdir(exist_ok=True)
    (bctx.workdir / "LoginPage.java").write_text(
        "package a;\npublic class LoginPage {\n  public void login() {}\n}\n",
        encoding="utf-8",
    )
    index = RepositoryIndex(bctx.workdir)
    try:
        index.rebuild()
        hits = index.find_symbols("LoginPage", kind="class")
        ok = bool(hits) and hits[0]["name"] == "LoginPage"
    finally:
        index.close()
    return ok, 1, "found symbol" if ok else "symbol not found", {}


# -- code generation (coding) -----------------------------------------------

def _task_code_generation(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (bctx.workdir / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    agent = _coding_agent(bctx)
    plan = agent.plan("Create calc.py with add(a, b) returning a + b so tests pass.")
    if plan.validation_errors or not plan.edit_plan.ops:
        return False, 0, "no valid plan", {}
    agent.apply(plan, _fs(bctx))
    result = _run_pytest(bctx.workdir)
    return result.passed, 1, "tests pass" if result.passed else "tests fail", {}


# -- test fixing (coding) ---------------------------------------------------

def _task_test_fixing(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (bctx.workdir / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (bctx.workdir / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    agent = _coding_agent(bctx)
    debug = DebugAgent(bctx.workdir, bctx.provider, bctx.router, bctx.registry, bctx.config)
    fs = _fs(bctx)
    iterations = 0
    for iterations in range(1, 3):
        result = _run_pytest(bctx.workdir)
        if result.passed:
            return True, iterations, "fixed", {}
        plan = agent.plan(debug.fix_request(result))
        if plan.validation_errors or not plan.edit_plan.ops:
            return False, iterations, "no fix", {}
        agent.apply(plan, fs)
    final = _run_pytest(bctx.workdir)
    return final.passed, iterations, "fixed" if final.passed else "not fixed", {}


# -- refactoring (coding) ---------------------------------------------------

def _task_refactoring(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (bctx.workdir / "greeter.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    (bctx.workdir / "test_greet.py").write_text(
        "from greeter import greet\n\ndef test_greet():\n    assert greet() == 'hello'\n",
        encoding="utf-8",
    )
    agent = _coding_agent(bctx)
    plan = agent.plan("Change greet() in greeter.py to return 'hello'.")
    if plan.validation_errors or not plan.edit_plan.ops:
        return False, 0, "no valid plan", {}
    agent.apply(plan, _fs(bctx))
    result = _run_pytest(bctx.workdir)
    return result.passed, 1, "refactored" if result.passed else "failed", {}


# -- debugging (reasoning) --------------------------------------------------

def _task_debugging(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (bctx.workdir / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (bctx.workdir / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    result = _run_pytest(bctx.workdir)
    debug = DebugAgent(bctx.workdir, bctx.provider, bctx.router, bctx.registry, bctx.config)
    diagnosis = debug.diagnose(result)
    ok = bool(diagnosis.strip())
    return ok, 1, "produced diagnosis" if ok else "empty diagnosis", {}


# -- architecture analysis (reasoning) --------------------------------------

def _task_architecture(bctx: BenchContext) -> tuple[bool, int, str, dict]:
    (bctx.workdir / "svc.py").write_text(
        "class Service:\n    def handle(self, x):\n        return x * 2\n", encoding="utf-8"
    )
    model = bctx.router.model_for_intent("architecture")
    text = bctx.provider.generate(
        model, "Explain the responsibilities of this class:\n"
        + (bctx.workdir / "svc.py").read_text(encoding="utf-8"),
    ).text
    ok = bool(text.strip())
    return ok, 1, "produced analysis" if ok else "empty", {"model": model}


def default_suite() -> list[BenchmarkTask]:
    return [
        BenchmarkTask("context-retrieval", "context retrieval", _task_context_retrieval),
        BenchmarkTask("code-generation", "coding", _task_code_generation, required_role="coding"),
        BenchmarkTask("test-fixing", "test fixing", _task_test_fixing, required_role="coding"),
        BenchmarkTask("refactoring", "refactoring", _task_refactoring, required_role="coding"),
        BenchmarkTask("debugging", "debugging", _task_debugging, required_role="reasoning"),
        BenchmarkTask("architecture", "architecture analysis", _task_architecture, required_role="reasoning"),
    ]
