# Phase 14 — Benchmark Results

Harness: [`scripts/bench_orchestration.py`](../scripts/bench_orchestration.py).
It measures **objective, reproducible** metrics only — latency, model calls,
per-model status, and the result-status taxonomy. **Answer quality is NOT
auto-scored** (it needs human/real rating); quality is left to manual inspection
of `--real` outputs.

Reproduce:
```
python scripts/bench_orchestration.py              # MOCK — offline, deterministic
python scripts/bench_orchestration.py --real        # REAL — installed Ollama models
python scripts/bench_orchestration.py --real --limit 2
```

Mock vs real results are kept strictly separate (spec §9.2). Mock runs require no
daemon and no downloads.

## Dataset (fixtures)

5 tasks spanning categories: factual-explain, error-diagnosis, code-understanding,
ambiguous-requirements, conflicting-approaches. (Definitions in the harness.)

## Mode 1 — MOCK (offline, deterministic)

Provider: `MockProvider` (no network). Roles: mock-fast:1b / mock-mid:3b /
mock-strong:8b. **Purpose:** prove the orchestration mechanics (call counts,
status, strategy) deterministically and offline — not performance.

```
task                 strategy  status             lat(s)  calls  models
factual-explain      single    complete_success      0.0      1       1
factual-explain      ensemble  complete_success     0.02      4       3
error-diagnosis      single    complete_success      0.0      1       1
error-diagnosis      ensemble  complete_success      0.0      4       3
... (all 5 tasks identical shape) ...
```

**Observation:** single = **1** model call; ensemble = **4** calls (3 independent
members + 1 synthesis). This is the deterministic cost signature of ensemble.

## Mode 2 — REAL (Ollama) — bounded run

- **Hardware:** CPU-only (no `nvidia-smi`), Windows 11.
- **Models (for this bounded run):** fast=`tinyllama`, coding/reasoning=`qwen3:1.7b`,
  embedding=`nomic-embed-text` (temporarily set to fast models so the run
  completes; the project default reasoning model is `llama3.1:8b`, which is
  slower). Config restored afterwards.
- **Command:** `bench_orchestration.py --real --limit 2`
- **Ollama:** 0.24.0. **Models were already installed — no downloads.**

```
task                 strategy  status             lat(s)  calls  models
factual-explain      single    complete_success      6.70      -       1
factual-explain      ensemble  complete_success     74.50      -       2
error-diagnosis      single    complete_success     10.25      -       1
error-diagnosis      ensemble  partial_success     178.28      -       1
```

(`calls` = `-` : the real `OllamaProvider` does not record call counts; only the
mock provider does. Honest limitation, not omitted.)

### Real-mode findings

1. **Ensemble latency is 7–17× single** on this CPU box (6.7s→74.5s;
   10.25s→178.28s). Multi-model is expensive — which is why ensemble/review are
   **opt-in flags**, never automatic.
2. **The status taxonomy works under real failure:** `error-diagnosis` ensemble
   returned **`partial_success`** — one member did not return a usable answer, so
   the system did **not** label it a full success. This is the Phase-14 hardening
   doing its job on real models, not a mock.
3. Both single runs returned `complete_success`.

## Honesty notes (spec §9.2)

- Latency/status are measured; **no quality scores, token counts, or confidence
  values are fabricated**.
- The real run is **bounded** (2 fixtures, fast models) to keep wall-clock
  reasonable on CPU. It is therefore **representative, not exhaustive** — a full
  5-fixture real run with `llama3.1:8b` would take far longer and is not required
  to demonstrate the mechanics.
- "Multi-model is better" is **not** claimed. The data shows ensemble costs more
  and can only reach `partial_success` when a member fails; its value (quality,
  disagreement detection) is qualitative and must be judged per task.

## Conclusion

The benchmark reproducibly demonstrates: correct call-count/strategy behaviour
(mock), real multi-model latency cost, and correct **partial-success reporting**
under a real member failure. Quality comparison remains a manual exercise.
