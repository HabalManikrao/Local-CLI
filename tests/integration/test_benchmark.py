"""Benchmark harness + tasks, and the dashboard command."""

from __future__ import annotations

import json

import pytest

from cle.benchmark.harness import (
    BenchContext,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkTask,
    summarize,
)
from cle.benchmark.tasks import _task_context_retrieval, default_suite
from cle.cli import commands
from cle.models.base import GenerateResult

from tests.conftest import FakeProvider, make_context


def _bctx(tmp_path, ctx):
    return BenchContext(ctx.provider, ctx.router, ctx.registry, ctx.config, tmp_path)


@pytest.mark.integration
def test_context_retrieval_task_local(tmp_path):
    ctx = make_context(tmp_path / "proj")
    (tmp_path / "proj").mkdir(exist_ok=True)
    work = tmp_path / "work"
    work.mkdir()
    ok, iters, note, _ = _task_context_retrieval(_bctx(work, ctx))
    assert ok is True


@pytest.mark.integration
def test_suite_skips_unconfigured_roles(tmp_path):
    ctx = make_context(tmp_path)  # no models configured
    suite = BenchmarkSuite(default_suite())
    results = suite.run(_bctx(tmp_path / "w", ctx))
    # context-retrieval runs; model tasks are skipped.
    by_name = {r.name: r for r in results}
    assert by_name["context-retrieval"].skipped is False
    assert by_name["code-generation"].skipped is True


@pytest.mark.integration
def test_suite_runs_model_task_with_provider(tmp_path):
    class CodeGenProvider(FakeProvider):
        def generate(self, model, prompt, *, system=None):
            plan = {"goal": "add", "changes": [
                {"op": "CREATE_FILE", "path": "calc.py",
                 "content": "def add(a, b):\n    return a + b\n", "explanation": "x"}]}
            return GenerateResult(text=json.dumps(plan), model=model)

    ctx = make_context(tmp_path, provider=CodeGenProvider(), models={"coding": "c"})
    # Run just the code-generation task.
    task = next(t for t in default_suite() if t.name == "code-generation")
    suite = BenchmarkSuite([task])
    results = suite.run(_bctx(tmp_path / "w", ctx))
    assert results[0].success is True
    assert results[0].latency_s >= 0


def test_summarize():
    results = [
        BenchmarkResult("a", "coding", True, False, 1.0, 1),
        BenchmarkResult("b", "coding", False, False, 2.0, 1),
        BenchmarkResult("c", "coding", None, True, 0.0, 0),
    ]
    s = summarize(results)
    assert s["ran"] == 2 and s["passed"] == 1 and s["skipped"] == 1
    assert s["success_rate"] == 0.5


@pytest.mark.integration
def test_cmd_benchmark_stores_results(tmp_path):
    ctx = make_context(tmp_path)  # no models → model tasks skipped, local runs
    code = commands.cmd_benchmark(ctx)
    assert code == 0
    out = list((tmp_path / ".cle" / "benchmarks").glob("benchmark-*.json"))
    assert out
    payload = json.loads(out[0].read_text())
    assert "summary" in payload and "results" in payload and "system" in payload


@pytest.mark.integration
def test_cmd_dashboard(tmp_path, capsys):
    ctx = make_context(tmp_path, models={"coding": "c"})
    assert commands.cmd_dashboard(ctx) == 0
    out = capsys.readouterr().out
    assert "dashboard" in out.lower()
    assert "Models" in out
