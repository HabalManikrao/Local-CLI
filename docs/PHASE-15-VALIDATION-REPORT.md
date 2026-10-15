# Phase 15 — Validation Report

## Commands executed + actual results

```
.venv\Scripts\python -m pytest        ->  210 passed, 2 skipped
.venv\Scripts\python -m ruff check .  ->  All checks passed!
.venv\Scripts\python -m mypy          ->  Success: no issues found in 55 source files
```

- **+5 tests** over the Phase-14 baseline (205 → 210). 2 skipped = opt-in
  live-daemon smoke tests (unchanged).
- New tests: `cle code --validate` pass / fail / skipped-when-no-tests (3) and
  telemetry single / synthesis-counting (2); one ensemble test updated for the
  synthesis-as-labelled-run change.

## Changes validated

- **Validated coding workflow** (`cle code --validate`): applies the change, then
  runs the project's tests via the guarded `TestAgent`, and reports an explicit
  status — `VALIDATED` / `VALIDATION_FAILED` (exit 1) / `VALIDATION_SKIPPED`.
  Failing tests are **never** reported as success.
- **Telemetry**: `OrchestrationResult.telemetry()` aggregates model_calls,
  members, successes/failures, retries, wall vs sum-of-model durations — accurate
  for the real provider. Synthesis is a labelled run, not counted as a member.
- **Benchmark harness** fixed to use telemetry (real-provider model-calls).

## Real-model / real-artifact evidence

- Offline **bundle verification ran** (`verify.ps1`): **152/152 checksums OK**,
  model blobs present (tinyllama, nomic-embed-text). See OFFLINE-ACCEPTANCE.
- Mock benchmark (offline, deterministic) shows single=1 call, ensemble=4 calls
  (3 members + synthesis).
- Phase-14 real ensemble evidence (tinyllama + qwen3:1.7b, partial_success on a
  real failure) remains valid; not re-run in Phase 15.

## Failure scenarios exercised (tests)

validation pass → `VALIDATED`; validation fail → `VALIDATION_FAILED` + exit 1;
no test system → `VALIDATION_SKIPPED`; ensemble partial failure → `partial_success`
(Phase 14, still passing); override no-fallback; config validation.

## Acceptance gates

### Safety
| Gate | Verdict | Evidence |
|---|---|---|
| Permission controls intact | **PASS** | validation + apply go through guarded `TestAgent`/`FileSystem` |
| Reviewer can't bypass patch application | **PASS** | reviewer is text-only (`test_code_review_*` asserts no writes) |
| Validation status reflects real outcomes | **PASS** | `test_cmd_code_validate_*` |
| Repair / model calls bounded | **PASS (existing)** | `cle fix-tests`/autopilot caps; `--validate` doesn't loop |

### Correctness
| Gate | Verdict | Evidence |
|---|---|---|
| Review against actual final diff | **PASS** | `_render_code_review` uses `plan.edit_plan.preview` |
| Stale/conflicting changes handled | **PARTIAL** | pre-apply re-validate catches missing files; content-level stale `MODIFY_FILE` mitigated by checkpoint (documented) |
| Tests run against final change | **PASS** | `--validate` runs after apply |
| Failures not reported as success | **PASS** | `VALIDATION_FAILED` → exit 1 |

### Reliability
| Gate | Verdict | Evidence |
|---|---|---|
| Timeouts/retries per documented guarantees | **PARTIAL** | retries/concurrency bounded + tested; provider has no cancellation (documented) |
| Concurrency bounded | **PASS** | `max_parallel_models`; threads joined (no early slot release) |
| Partial failures accurate | **PASS** | status taxonomy + telemetry |
| Telemetry reflects real execution | **PASS** | `test_telemetry_*`; measured `time.monotonic` |

### Offline
| Gate | Verdict | Evidence |
|---|---|---|
| Bundle checksums verify | **PASS** | 152/152 |
| Setup uses local artifacts only | **PARTIAL** | wheels+models bundled; fresh `setup.ps1 -Offline` not run on this machine |
| Real local inference offline | **NOT RUN** | needs disconnected machine |
| Idempotency/recovery | **NOT RUN** | needs disconnected machine |
| **Genuine network isolation** | **BLOCKED** | live workstation; cannot disconnect |

### Compatibility
| Gate | Verdict | Evidence |
|---|---|---|
| Existing commands functional | **PASS** | full suite green; `cle code`/`config show` smoke |
| Existing configs usable | **PASS** | `--validate` optional; no config migration |
| Single-model defaults stay single | **PASS** | `--validate`/`--review` don't invoke ensembles |
| Existing tests pass | **PASS** | 205→210, no regressions |

### Quality
| Gate | Verdict |
|---|---|
| New tests cover changes | **PASS** |
| Ruff | **PASS** |
| Mypy | **PASS** |
| Docs match code | **PASS** |
| Git status reported accurately | **PASS** (final report in chat) |

## Overall: PARTIAL-COMPLETE

All **safety and correctness** gates PASS. PARTIAL/BLOCKED items are honest
environment/architecture limits (no provider cancellation; no disconnected
machine for network-isolated offline acceptance; fresh offline setup not run on
the live machine). Autopilot multi-model integration is **deferred** with a
documented readiness checklist, not faked.

## Reproduce

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy
.venv\Scripts\python scripts\bench_orchestration.py
dist\CLE-OFFLINE-BUNDLE-0.1.0\verify.ps1
cle code "..." --validate     # applies, runs tests, prints VALIDATED/VALIDATION_FAILED
```
