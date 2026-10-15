# Phase 16 — Evaluation Plan

## Scope

Establish reproducible evidence of CLE's real engineering capability and decide
release readiness. Evaluation is **evidence-driven**: objective ground truth over
model self-evaluation; model agreement is never treated as correctness.

## Task categories & how each is evaluated

| Category | Method | Ground truth | Runnable |
|---|---|---|---|
| Symbol lookup | `index.find_symbols` vs defining file | repo source (independent) | **deterministic** (`bench_engineering.py`) |
| Source discovery / exact retrieval | `exact_search` vs known-relevant files | repo source | **deterministic** |
| Semantic retrieval | recall@k | labelled queries | **not scored** (needs labelled set + embeddings) |
| Error diagnosis / root cause | `cle debug` vs seeded defect | seeded fixture | real-model (bounded) |
| Small bounded code modification | `cle code --validate` on seeded defect | failing→passing test | **real-model** (done) |
| Patch validation | objective tests after apply | test outcome | **real-model** (done) |
| Regression-test generation | manual review | — | not automated |
| Independent review | `--review`; independence reported | — | covered by unit tests |
| Multi-model disagreement | ensemble synthesis flags disagreement | — | real-model (Phase 14 evidence) |
| Unsupported-claim detection | synthesis prompt discards unsupported | — | qualitative |

## Ground-truth methodology

- **Deterministic tasks:** ground truth is the actual repository structure
  (which file defines a symbol; which files contain a pattern), fixed in the
  harness **before** running, independent of tool output.
- **Coding tasks:** ground truth is an **objective test** (seeded defect →
  failing test that must pass), in a **disposable** fixture — never the user's
  project. A patch is "correct" only if the test passes and unrelated source is
  unchanged.
- Diagnosis hypotheses are classified: confirmed (objective evidence) /
  plausible / unverified / incorrect. A diagnosis is "confirmed" only with
  objective support.

## Metric definitions (fixed before running)

- **symbol-lookup success** = fraction of symbols whose defining file is returned.
- **recall** = relevant files found / relevant files expected.
- **precision (proxy)** = relevant files / distinct files returned (note: exact
  grep returns all occurrences, so precision < 1 is expected).
- **validation status** = VALIDATED / VALIDATION_FAILED / VALIDATION_SKIPPED from
  objective tests (not model opinion).
- **cost** = model calls + measured wall-clock latency (from orchestrator
  telemetry).

## Real vs mocked separation

- Deterministic benchmark: no model (offline, reproducible).
- Unit/integration tests: mocked providers.
- Real-model: explicitly labelled runs on the live Ollama daemon with named
  models (e.g. qwen3:1.7b); never auto-downloaded.
- Offline acceptance: bundle checksum verification; network-isolation marked
  BLOCKED where a disconnected machine is unavailable.

## Known limitations

- Small real-model sample on CPU (not statistical).
- Semantic-retrieval recall not scored.
- Answer quality not auto-scored; objective tests are the coding ground truth.
- Diagnosis/coding evaluated on seeded fixtures, not a large real-defect corpus.
