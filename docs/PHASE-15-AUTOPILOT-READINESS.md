# Phase 15 — Autopilot Readiness

**Status: multi-model orchestration is NOT integrated into `cle autopilot`
(deferred by design).** This document records autopilot's current boundaries and
the gates required before any future integration.

## Current autopilot boundaries (audited in `cmd_autopilot`)

| Control | Present? | Mechanism |
|---|---|---|
| Bounded iterations | **Yes** | `autonomous.max_iterations` (default 5), `--max-iter` |
| Per-change approval | **Yes** | `autonomous.require_approval` (default true) → `_apply_with_approval` |
| Permission guard on writes/shell | **Yes** | `PermissionGuard` + guarded `FileSystem`; `autonomous.allow_delete` |
| Checkpoint before edits | **Yes** | git checkpoint (`autonomous.require_git`) → `cle rollback` |
| Objective validation | **Yes** | `TestAgent.run` (guarded `run_tests`) each iteration |
| Diff inspection | **Yes** | `_render_plan` + diff preview before apply |
| Auto commit / push | **No (good)** | applies to working tree only; never commits/pushes |
| Model selection | **Single-model** | coding/reasoning roles; **no ensemble / no multi-model** |
| Arbitrary model shell commands | **No** | only the detected/configured test command, through the guard |

Autopilot is already a *bounded, approval-gated, git-protected, objectively
validated* single-model loop. That is why Phase 15 does **not** bolt
multi-model orchestration onto it: the added latency/cost and the risk of
unbounded model calls would not be matched by a clear safety benefit yet.

## Gates required before multi-model autopilot integration

1. **Explicit opt-in** flag/config (never on by default).
2. **Bounded model calls per task** (hard cap across all stages, not per stage).
3. **Bounded repair attempts** with a single overall deadline.
4. **Review independence** enforced or reported (different model from the coder).
5. **Objective validation gates each apply** (already present) — a multi-model
   review must never substitute for tests.
6. **No approval bypass:** ensemble/review output cannot auto-approve a patch.
7. **Resource governance:** respect `max_parallel_models`; no overlapping retries.
8. **Telemetry per stage** (now available via `OrchestrationResult.telemetry()`).
9. **Deterministic failure/stop** when the model-call or repair budget is spent.
10. **Documented, reproducible behaviour** + regression tests for each gate.

## Non-invasive improvements considered (and their status)

- Per-iteration telemetry: **available** (telemetry()); could be surfaced in
  autopilot output in a future phase without changing control flow.
- Independent review step: would require an ensemble/second model — deferred
  because it adds unbounded cost to the loop.

No autopilot code was changed in Phase 15.
