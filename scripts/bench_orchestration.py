"""Reproducible orchestration benchmark: single vs ensemble strategies.

Measures OBJECTIVE, reproducible metrics only — latency, model calls, per-model
status, and the result-status taxonomy. It does NOT score answer *quality*
(that needs human/real rating and is out of scope for an automated harness);
quality is left to manual review of the printed outputs in --real mode.

Usage:
    python scripts/bench_orchestration.py            # mock provider (offline, deterministic)
    python scripts/bench_orchestration.py --real      # real Ollama, using this project's config

Mock mode is fully offline and deterministic (no daemon, no downloads). Real
mode uses the installed models already configured via `cle model use`; it never
triggers downloads.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cle.config import Config, load_config  # noqa: E402
from cle.models.base import GenerateResult, Health, ModelInfo, ModelProvider  # noqa: E402
from cle.models.orchestrator import Orchestrator  # noqa: E402
from cle.models.registry import ModelRegistry  # noqa: E402
from cle.models.router import ModelRouter  # noqa: E402

# Small benchmark fixture set (task category, intent, prompt).
FIXTURES = [
    ("factual-explain", "simple_question", "In one sentence, what is a hash map?"),
    ("error-diagnosis", "simple_question", "What does 'IndexError: list index out of range' mean?"),
    ("code-understanding", "simple_question", "What does a Python context manager do?"),
    ("ambiguous", "simple_question", "Compare recursion and iteration."),
    ("conflicting", "architecture", "Design a rate limiter — token bucket vs sliding window?"),
]


class MockProvider(ModelProvider):
    """Deterministic offline provider; records calls, varies text per model."""

    def __init__(self):
        self.calls: list[str] = []
        self._installed = [
            ModelInfo(name="mock-fast:1b", parameter_size="1B"),
            ModelInfo(name="mock-mid:3b", parameter_size="3B"),
            ModelInfo(name="mock-strong:8b", parameter_size="8B"),
        ]

    def health(self):
        return Health(ok=True, detail="mock", host="mock")

    def list_models(self):
        return list(self._installed)

    def generate(self, model, prompt, *, system=None):
        self.calls.append(model)
        return GenerateResult(text=f"[{model}] answer to: {prompt[:40]}", model=model)

    def chat(self, model, messages):
        return GenerateResult(text=f"[{model}] chat", model=model)

    def stream(self, model, messages):
        yield f"[{model}] streamed"

    def embed(self, model, text):
        return [0.0]


def _mock_config(tmp: Path) -> Config:
    from cle.config import init_project_config, set_project_value
    init_project_config(tmp)
    for role, m in {"fast": "mock-fast:1b", "coding": "mock-mid:3b",
                    "reasoning": "mock-strong:8b", "embedding": "mock-embed"}.items():
        set_project_value(tmp, f"models.{role}", m)
    return load_config(tmp)


def _build(real: bool):
    if real:
        config = load_config(ROOT)
        from cle.models.ollama import OllamaProvider
        provider = OllamaProvider(
            host=config.get("provider.host", "http://127.0.0.1:11434"),
            timeout_seconds=float(config.get("provider.timeout_seconds", 300)),
            num_ctx=(int(config.get("provider.num_ctx")) if config.get("provider.num_ctx") else None),
        )
    else:
        import tempfile
        provider = MockProvider()
        config = _mock_config(Path(tempfile.mkdtemp()))
    reg = ModelRegistry(config)
    return Orchestrator(provider, ModelRouter(config, reg), reg, config), provider


def _run(orch, intent, prompt, ensemble):
    start = time.monotonic()
    try:
        res = orch.run_text(intent, prompt, ensemble=ensemble)
        # Telemetry comes from the orchestrator's own ModelRun records, so
        # model_calls is accurate for the REAL provider too (not mock-only).
        t = res.telemetry()
        return {"ok": True, "status": res.status, "latency_s": round(t["wall_s"], 2),
                "model_calls": t["model_calls"], "strategy": res.decision.strategy,
                "n_models": t["successes"]}
    except Exception as exc:  # noqa: BLE001 — benchmark records failures too
        return {"ok": False, "status": "failed", "error": str(exc)[:60],
                "latency_s": round(time.monotonic() - start, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="use real Ollama (installed models)")
    ap.add_argument("--limit", type=int, default=0, help="only run the first N fixtures")
    args = ap.parse_args()
    mode = "REAL (Ollama)" if args.real else "MOCK (offline, deterministic)"

    orch, _provider = _build(args.real)
    print(f"# Orchestration benchmark - {mode}")
    print(f"{'task':<20} {'strategy':<9} {'status':<17} {'lat(s)':>7} {'calls':>6} {'models':>7}")
    print("-" * 72)
    fixtures = FIXTURES[: args.limit] if args.limit else FIXTURES
    for name, intent, prompt in fixtures:
        for ens in (False, True):
            r = _run(orch, intent, prompt, ens)
            strat = "ensemble" if ens else "single"
            if r["ok"]:
                print(f"{name:<20} {strat:<9} {r['status']:<17} {r['latency_s']:>7} "
                      f"{r['model_calls']:>6} {r.get('n_models', 1):>7}")
            else:
                print(f"{name:<20} {strat:<9} {'FAILED':<17} {r['latency_s']:>7}   {r.get('error','')}")
    print("\nNote: latency/calls are objective; answer QUALITY is not auto-scored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
