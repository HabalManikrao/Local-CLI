"""Benchmark harness.

A :class:`BenchmarkTask` runs a single scenario and reports success + metrics;
the :class:`BenchmarkSuite` times each task, skips tasks whose required model
role is unset, and aggregates results. Timing uses ``time.perf_counter``.

Resource metrics (GPU/RAM) are best-effort and simply omitted when unavailable
(honest reporting per the audit's Windows/GPU caveats).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..models.base import ModelProvider
from ..models.registry import ModelRegistry
from ..models.router import ModelRouter


@dataclass
class BenchContext:
    provider: ModelProvider
    router: ModelRouter
    registry: ModelRegistry
    config: Config
    workdir: Path                 # a scratch directory the task may use


@dataclass
class BenchmarkResult:
    name: str
    category: str
    success: bool | None          # None = not applicable / skipped
    skipped: bool
    latency_s: float
    iterations: int
    note: str = ""
    metrics: dict = field(default_factory=dict)


# A task returns (success, iterations, note, metrics).
TaskFn = Callable[[BenchContext], "tuple[bool, int, str, dict]"]


@dataclass
class BenchmarkTask:
    name: str
    category: str
    fn: TaskFn
    required_role: str | None = None   # skip if this model role is unset


class BenchmarkSuite:
    def __init__(self, tasks: list[BenchmarkTask]):
        self.tasks = tasks

    def run(self, ctx: BenchContext) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for task in self.tasks:
            if task.required_role and not (ctx.config.get(f"models.{task.required_role}", "")):
                results.append(BenchmarkResult(
                    name=task.name, category=task.category, success=None,
                    skipped=True, latency_s=0.0, iterations=0,
                    note=f"skipped: no '{task.required_role}' model configured",
                ))
                continue
            work = ctx.workdir / task.name
            work.mkdir(parents=True, exist_ok=True)
            task_ctx = BenchContext(ctx.provider, ctx.router, ctx.registry, ctx.config, work)
            start = time.perf_counter()
            try:
                success, iterations, note, metrics = task.fn(task_ctx)
            except Exception as exc:  # a failing task must not abort the suite
                results.append(BenchmarkResult(
                    name=task.name, category=task.category, success=False,
                    skipped=False, latency_s=time.perf_counter() - start,
                    iterations=0, note=f"error: {exc}",
                ))
                continue
            results.append(BenchmarkResult(
                name=task.name, category=task.category, success=success,
                skipped=False, latency_s=round(time.perf_counter() - start, 4),
                iterations=iterations, note=note, metrics=metrics,
            ))
        return results


def summarize(results: list[BenchmarkResult]) -> dict:
    ran = [r for r in results if not r.skipped]
    passed = [r for r in ran if r.success]
    return {
        "total": len(results),
        "ran": len(ran),
        "skipped": len(results) - len(ran),
        "passed": len(passed),
        "success_rate": round(len(passed) / len(ran), 3) if ran else None,
        "total_latency_s": round(sum(r.latency_s for r in ran), 4),
    }
