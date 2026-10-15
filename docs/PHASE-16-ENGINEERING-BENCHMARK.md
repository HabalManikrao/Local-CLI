# Phase 16 — Engineering Benchmark

Two benchmarks: a **deterministic** one (no model, reproducible offline) and a
**controlled real-model** coding evaluation on a disposable seeded-defect fixture.
Mocked/deterministic and real-model results are kept separate.

## 1. Deterministic benchmark (offline, no LLM)

Harness: [`scripts/bench_engineering.py`](../scripts/bench_engineering.py).
Ground truth is defined in the harness from the actual source (independent of
tool output). Run:

```
cle index                                   # build the index first
python scripts/bench_engineering.py
```

### Symbol lookup (ground truth = defining file)

10 real symbols (`Orchestrator`, `ModelRouter`, `PermissionGuard`, `CodingAgent`,
`EvidenceSource`, `run_tests`, `OllamaProvider`, …). For each, check that
`index.find_symbols()` returns the known-correct defining file.

**Result: 10/10 (100%) HIT**, ~0 ms each (SQLite index).

### Exact retrieval (ground truth = known relevant files)

| pattern | found/expected | recall | precision | files | ms |
|---|---|---|---|---|---|
| `class Orchestrator` | 1/1 | 1.00 | 0.50 | 2 | 47 |
| `ModelNotConfiguredError` | 2/2 | 1.00 | 0.40 | 5 | 32 |
| `def run_tests` | 1/1 | 1.00 | 0.50 | 2 | 31 |
| `STATUS_PARTIAL` | 1/1 | 1.00 | 0.50 | 2 | 31 |

**Mean recall 1.00, mean precision 0.47.** Recall is perfect — every known-relevant
file is found. The ~0.47 precision is **expected, not a defect**: exact search
returns *all* files containing the pattern (definitions **and** tests/usages), by
design. Interpreting these as a ranking task would need relevance weighting, which
exact grep does not do.

**Conclusion:** structural navigation (symbol lookup, exact retrieval) is
accurate and fast. This is the capability a model's context retrieval rests on.

## 2. Controlled real-model coding evaluation

Fixture (disposable scratch dir, **not** the user's project): `calc.py` with a
seeded defect (`add` returns `a - b`) and `test_calc.py` asserting
`add(2,3)==5`. Baseline: `1 failed` (`assert -1 == 5`). Ground truth: change
`a - b` → `a + b`; only `calc.py` should change.

Command (real model):
```
cle code "Fix the add function in calc.py so it returns a + b. The test
          expects add(2,3)==5." --model qwen3:1.7b --validate --yes
```

**Observed (real run, ~1m44s):**
- Goal identified: *"Fix the add function to return a + b instead of a - b"*.
- Change: `MODIFY_FILE: calc.py` (correct, single file).
- Checkpoint created before apply (safety).
- Objective validation ran: `PASS — system python … pytest`.
- **Status: VALIDATED.**
- Independent verification: `pytest` → **1 passed**.
- `git status`: only `M calc.py` (plus CLE's own `.cle/`, `logs/`, `__pycache__`
  artifacts — not source changes).

**Conclusion:** the validated coding workflow correctly diagnosed, fixed the right
file through the permission-guarded path, ran objective tests, and reported an
honest `VALIDATED` confirmed by an independent test run. (Single task, single
model — representative, not a statistical claim.)

## 3. Single-model vs multi-model (cost vs value)

From the Phase-14/15 orchestration benchmark (real Ollama, CPU):

| metric | single | ensemble |
|---|---|---|
| model calls | 1 | 4 (3 members + 1 synthesis) |
| latency (factual) | ~6.7 s | ~74.5 s (**~11×**) |
| latency (diagnosis) | ~10.25 s | ~178 s (**~17×**) |
| failure handling | n/a | correctly reported `partial_success` on a real member failure |

On the Phase-16 coding task, a **single** small model (qwen3:1.7b) solved it
(`VALIDATED`) — multi-model was not needed.

**Finding:** ensemble costs 7–17× the latency and 4× the calls. On these tasks it
produced no *measured* quality improvement (the single model already passed
objective validation); its value (disagreement detection) is qualitative and
best reserved for genuinely ambiguous, high-stakes questions. **Evidence sample
is small — treat the quality comparison as inconclusive, the cost as clear.**

## Known limitations

- Real-model tasks are a small sample (1 coding task, a handful of ensemble
  prompts) on CPU; not a statistical benchmark.
- Semantic-retrieval recall@k was not scored here (would need a labelled query
  set and a built embedding index); the deterministic structural retrieval was.
- Quality of model answers is not auto-scored — objective validation (tests) is
  the ground truth for coding; diagnosis quality is judged qualitatively.
