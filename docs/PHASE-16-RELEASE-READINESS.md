# Phase 16 — Release Readiness

## Repository baseline (verified)

- `master` @ `1a02249` (Phase 15); audited clean and in sync before Phase 16.
- Version: `0.1.0` (single-sourced via `cle.__version__`, dynamic in pyproject).

## Test & quality results (actual)

```
pytest  -> 210 passed, 2 skipped       (2 skipped = opt-in live-daemon smoke)
ruff    -> All checks passed!
mypy    -> Success: no issues found in 55 source files
```

## Capability evidence (Phase 16)

| Area | Evidence | Result |
|---|---|---|
| Symbol lookup | `bench_engineering.py` vs ground truth | **10/10 (100%)** |
| Exact retrieval | same | **recall 1.00**, precision 0.47 (expected) |
| Validated coding | real `cle code --validate` on seeded defect | **VALIDATED**, confirmed by independent `pytest` |
| Permission safety | guarded apply + checkpoint | only target file changed |
| Multi-model cost | real orchestration benchmark | ensemble 7–17× slower; `partial_success` on real failure |

## Safety audit

| Property | Verdict | Evidence |
|---|---|---|
| Override never silently swaps model | **PASS** | `test_override_does_not_fall_back` |
| Fallback/escalation bounded | **PASS** | retry/escalation tests |
| Parallel execution bounded | **PASS** | `max_parallel_models`; threads joined |
| Timeout honesty (no false cancel) | **PASS** | documented; provider timeout is the bound |
| Partial ensemble ≠ success | **PASS** | `test_status_partial_*`; real `partial_success` |
| Advisory review ≠ validation | **PASS** | `--review` vs `--validate` distinct; `test_cmd_code_validate_*` |
| Reviewer can't modify files | **PASS** | `test_code_review_reports_non_independence` |
| Validation not faked | **PASS** | `VALIDATION_FAILED` → exit 1 |
| Permission controls intact | **PASS** | apply/validate go through guard |
| No unexpected model downloads | **PASS** | discovery lists only; no pulls in code |
| Single-model backward compat | **PASS** | full suite green; defaults unchanged |

## Offline status

- Bundle verification: **PASS** (152/152 checksums; model blobs present).
- Genuine network-isolated acceptance: **BLOCKED** (no disconnected machine;
  live workstation). See `PHASE-15-OFFLINE-ACCEPTANCE.md`.

## Acceptance gates (Phase 16)

| # | Gate | Verdict |
|---|---|---|
| 1 | Baseline verified | PASS |
| 2 | Benchmark has documented acceptance criteria | PASS |
| 3 | Real-project understanding vs source evidence | PASS (CLE repo) |
| 4 | Retrieval vs independent ground truth | PASS |
| 5 | Coding in controlled copies | PASS (scratch fixture) |
| 6 | Patches evaluated with objective tests | PASS |
| 7 | Multi-model compared fairly to single | PARTIAL (small sample; cost clear, quality inconclusive) |
| 8 | Latency/call overhead measured | PASS |
| 9 | Safety/regression audit | PASS |
| 10 | Suite + ruff + mypy pass | PASS |
| 11 | Offline bundle verification | PASS |
| 12 | Network-isolated acceptance | **BLOCKED** |
| 13 | Docs/benchmark reproducible | PASS |
| 14 | Release readiness evidence-based | PASS (this doc) |
| 15 | Git status accurate | PASS |

## Release recommendation: **READY WITH KNOWN LIMITATIONS**

As a **local, offline, single-/multi-model engineering assistant**, CLE is
functional, tested (210 green), lint/type-clean, safety-audited, and
demonstrably able to navigate code, propose a correct fix, and validate it
objectively. A `0.1.0` tag is justified **with the limitations below documented**.

This is **not** a claim of universal production-readiness.

### Known limitations (must ship in release notes)
- **Answer quality is bounded by the local model** and the hardware (CPU latency
  is minutes for 8B models); small models give weaker results.
- **Multi-model value is unproven on quality** (small sample); it is 7–17× more
  expensive — keep it opt-in, single-model default.
- **Network-isolated offline acceptance is BLOCKED** (verified by checksums +
  dependency inspection only).
- **Autopilot multi-model orchestration is deferred** (readiness checklist).
- Real-model evaluation is a small sample, not a statistical benchmark.

### Not done here (by rule)
No tag was created, no package published, no version bumped — a release action
requires explicit authorization per the project workflow.
