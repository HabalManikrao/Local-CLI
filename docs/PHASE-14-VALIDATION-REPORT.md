# Phase 14 — Validation Report

**Scope:** harden the Phase-13 multi-model orchestration (correctness, safety,
reliability, observability, benchmarking) without breaking existing commands.

## Baseline (verified, not assumed)

Ran the suite before changes: **193 passed / 2 skipped**, ruff clean, mypy clean,
working tree clean, `master` at `4ee7db6` and in sync with origin.

## Changes made

| File | Change |
|---|---|
| `cle/models/orchestrator.py` | config `validate()`; `STATUS_*` taxonomy; `RoutingDecision.{is_override,escalated,notes}`; `ModelRun.{attempts,duration_s}`; `OrchestrationResult.{status,duration_s}`; override **no-fallback**; `_run_single`/`_run_ensemble` set status; `_invoke` (measured, non-raising, retry-counting); timeout honesty comment |
| `cle/cli/commands.py` | `_render_runs` shows duration/attempts/status; `_render_code_review` reports review **independence** and that it is advisory; passes the coder model in |
| `configs/default.yaml` | (unchanged this phase — orchestration block from P13) |
| `scripts/bench_orchestration.py` | **new** reproducible benchmark (mock + `--real`) |
| `tests/unit/test_orchestrator.py` | +12 Phase-14 tests |
| `docs/PHASE-14-*.md`, `docs/USAGE.md`, `CHANGELOG.md` | documentation |

No new runtime dependencies (`orchestrator.py` imports only `time`,
`concurrent.futures`, `dataclasses` from stdlib). `pyproject.toml` dependencies
unchanged.

## Test results (actual, executed)

```
.venv\Scripts\python -m pytest        ->  205 passed, 2 skipped
.venv\Scripts\python -m ruff check .  ->  All checks passed!
.venv\Scripts\python -m mypy          ->  Success: no issues found in 55 source files
```

- **+12 tests** over baseline (193 → 205). 2 skipped = opt-in live-daemon smoke
  tests (unchanged).
- New tests cover: config validation (bad strategy/priority/limits), override
  no-fallback, status taxonomy (complete/fallback/partial), retry-attempt
  recording, deterministic routing, review independence (both directions),
  reviewer-is-text-only (no file writes).

## Real-model evidence

- `cle config show` and `cle ask --model qwen3:1.7b` run live (routing line shown).
- Live ensemble (`tinyllama` + `qwen3:1.7b`) synthesised an answer and flagged
  disagreement (~70s).
- Benchmark `--real --limit 2`: single 6.7s/10.25s vs ensemble 74.5s/178.28s;
  one ensemble correctly reported **`partial_success`** on a real member failure.
  Full numbers in [PHASE-14-BENCHMARK-RESULTS.md](PHASE-14-BENCHMARK-RESULTS.md).

## Failure scenarios exercised (tests)

model-unavailable → fallback (non-override) and **no-fallback (override)**;
transient failure → retry; all-models-fail → raise; ensemble partial failure →
`partial_success`; ensemble all-fail → raise; synthesis failure → first answer;
invalid config → `ConfigError`.

## Offline validation

- Orchestration adds **no third-party dependency** (stdlib only).
- Portable bundle refreshed; `dist/CLE-Install/configs/default.yaml` contains the
  `orchestration:` block.
- The entire test suite runs with **no network and no daemon** (providers mocked);
  mock benchmark runs fully offline and deterministically.
- Not independently re-verified with the network physically disabled; claim is
  "no network calls are made by the test suite / mock paths," evidenced by
  mocked providers and stdlib-only imports.

## Acceptance gates

| # | Gate | Verdict | Evidence |
|---|---|---|---|
| 1 | Audit + gap analysis | **PASS** | PHASE-14-GAP-ANALYSIS.md |
| 2 | Backward compatibility | **PASS** | all prior tests still pass; default command behaviour unchanged |
| 3 | Routing/override/caps/fallback tested | **PASS** | `test_route_*`, `test_override_*`, `test_build_profiles_*` |
| 4 | Bounded concurrency/retry/timeout/escalation | **PARTIAL** | retries/escalation bounded + tested; **timeout cannot cancel** the provider call (documented, not faked) |
| 5 | Review uses actual diff; reviewer can't edit | **PASS** | `_render_code_review` passes the real diff; `test_code_review_*` asserts no file writes |
| 6 | Final validation runs against final patch | **PARTIAL** | `cle test`/`fix-tests` run tests against the applied patch; `--review` is advisory and does **not** auto-run tests (documented) |
| 7 | Ensemble disagreement + partial failure | **PASS** | `test_status_partial_*`, live `partial_success`, synthesis flags disagreement |
| 8 | Integrated workflows have regression tests | **PASS** | ask/code/debug/config_show integration tests |
| 9 | Full suite passes or failures classified | **PASS** | 205 passed / 2 skipped (skips are opt-in live) |
| 10 | Lint + type-check | **PASS** | ruff + mypy clean |
| 11 | Real multi-model execution demonstrated | **PASS** | live ensemble + real benchmark |
| 12 | Benchmark separates mock vs real | **PASS** | PHASE-14-BENCHMARK-RESULTS.md |
| 13 | Offline compatibility | **PASS** | stdlib-only; bundle config present |
| 14 | Docs reflect reality + limitations | **PASS** | these three docs + USAGE/CHANGELOG |
| 15 | Git status accurately reported | **PASS** | see final report in chat |
| D | Autopilot orchestration integration | **DEFERRED** | kept existing bounded loop; documented rationale (unbounded-cost risk) |

**Overall: PARTIAL-COMPLETE.** All critical correctness/safety gates PASS. Two
gates are PARTIAL for honest, environment/architecture reasons (no provider
cancellation; `--review` is advisory rather than auto-running tests), and
autopilot orchestration is explicitly DEFERRED rather than faked.

## Remaining risks / deferred

- Provider-level cancellation (would need Ollama support or a process-kill
  strategy) — out of scope.
- Resource-aware concurrency is a conservative cap, not VRAM-measured.
- Autopilot multi-model integration deferred (cost/safety).
- `--review` could optionally auto-run targeted tests in a future phase.

## Reproduce

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy
.venv\Scripts\python scripts\bench_orchestration.py            # mock
.venv\Scripts\python scripts\bench_orchestration.py --real --limit 2
.venv\Scripts\cle config show
```
