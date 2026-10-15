# Phase 15 — Implementation Report

## Baseline (verified, not assumed)

- Branch `master`, commit `cc624f8` confirmed present (`git cat-file -t cc624f8` → commit).
- Suite before changes: **205 passed / 2 skipped**; ruff clean; mypy clean (55 files); tree clean, in sync with origin.

## Audit findings → changes

| Area | Finding (actual code) | Change |
|---|---|---|
| Validated coding (A) | `cle code` applied + *suggested* `cle test`; no objective validation or explicit status | Added `--validate`: runs the project's tests (guarded `TestAgent`) against the **applied** change; explicit status taxonomy |
| Proposal/apply separation (A) | Already separated: `plan.edit_plan` is the proposal (no writes); `apply()` writes through the guarded `FileSystem`; reviewer is text-only | Documented; status taxonomy makes the lifecycle explicit |
| Review semantics (A/E) | `--review` was advisory but under-labelled | `--review` kept advisory (help text clarified); `--validate` is the objective path; independence already reported (Phase 14) |
| Telemetry (C) | Orchestrator already records per-model duration/attempts (real provider too); the **benchmark harness** wrongly read `provider.calls` (mock-only) | `OrchestrationResult.telemetry()` aggregation; synthesis tracked as a labelled run (not a "member"); harness now uses telemetry |
| Resource/cancellation (B) | `future.result(timeout)` does not cancel the provider call; `ThreadPoolExecutor` joins threads on exit (slots not released early); retries are sequential within `_invoke` (no overlapping attempts) | Verified + documented honestly; no false cancellation claim |
| Autopilot (F) | Already bounded (iterations, per-apply approval, permission guard, checkpoints, objective tests, single-model, no auto-commit) | **Not integrated** with orchestration (per spec); readiness checklist written |
| Offline (D) | Bundle verify + checksums exist | Ran bundle verification (152 files OK); network isolation BLOCKED on this live machine |

## Files modified / created

- `cle/cli/commands.py` — validated-coding status taxonomy (`CODE_*`),
  `_objective_validation`, `cle code --validate` flow.
- `cle/cli/main.py` — `--validate` flag + clearer `code` help.
- `cle/models/orchestrator.py` — `OrchestrationResult.telemetry()`; synthesis
  tracked as a labelled `ModelRun` (role `synthesizer`), not counted as a member.
- `scripts/bench_orchestration.py` — uses telemetry (accurate model-calls for the
  real provider).
- `tests/integration/test_coding_agent.py` — +4 validate tests.
- `tests/unit/test_orchestrator.py` — +2 telemetry tests (and one updated).
- `docs/PHASE-15-*.md`, `docs/USAGE.md`, `CHANGELOG.md`.

No new runtime dependencies (stdlib only). Backward compatible: without
`--validate`, `cle code` behaves as before (plus an explicit `Status: APPLIED`
line).

## Architecture decisions

- **Reuse over new subsystems:** objective validation reuses `TestAgent` →
  `run_tests` (already permission-guarded); no patch database, no parallel coding
  system. The proposal/apply separation already existed (`EditPlan`).
- **Honesty of status:** a missing test suite yields `VALIDATION_SKIPPED`, never a
  false `VALIDATED`; failing tests yield `VALIDATION_FAILED` with exit code 1.
- **Telemetry at the orchestration boundary** (not provider-specific), so it is
  accurate for real and mock providers alike.

## Deferred / not done (honest)

- **Bounded repair inside `cle code --validate`:** not added; the existing
  `cle fix-tests` already provides the tested bounded repair loop, and `--validate`
  points users there on failure. Avoids duplicating/complicating the loop.
- **Autopilot multi-model orchestration:** deferred (see AUTOPILOT-READINESS).
- **Coding-mode benchmark (single vs review vs validate):** methodology
  documented; not executed as an automated real benchmark (needs a fixture repo +
  coding model + per-run test execution). The single-vs-ensemble benchmark stands.
- **Provider cancellation / VRAM-measured concurrency:** architectural blockers
  (Ollama has no cancellation; no reliable VRAM introspection) — documented.

## Remaining risks

- `--validate` runs the project's full test command; on large suites this is slow
  (bounded only by the provider/test timeout).
- Content-level stale-diff for `MODIFY_FILE` is mitigated by the pre-apply
  checkpoint (rollback), not by hash comparison (documented limitation).
