# Phase 14 — Gap Analysis

Audit of the Phase-13 multi-model orchestration against the Phase-14 hardening
spec. Baseline at audit time: commit `4ee7db6`, **193 passed / 2 skipped**, ruff
+ mypy clean, working tree clean (verified by running the suite, not assumed).

Legend: **PASS** = implemented + tested · **PARTIAL** = implemented with stated
limits · **BLOCKED** = not feasible in this environment.

| # | Requirement | State before P14 | Evidence | Gap | Change made | Acceptance test |
|---|---|---|---|---|---|---|
| A1 | Routing inputs (type/complexity/caps/availability/preference/override) | Present | `orchestrator.route`, `classify_complexity`, `build_profiles` | Context-window + unknown-caps not represented | Documented as unknown (Ollama doesn't expose ctx window reliably); caps discovered from roles | `test_build_profiles_*` |
| A2 | Deterministic routing precedence | Implicit | `route()` order | Not documented/tested; override could silently fall back | Precedence documented (below); override disables fallback | `test_routing_is_deterministic`, `test_override_*` |
| A3 | Override never silently swaps model | **Violated** | `_run_single_with_fallback` fell back for overrides | **Critical** | `is_override` flag → fallback disabled for overrides; error reported | `test_override_does_not_fall_back` |
| A4 | Structured routing explanation | Partial | `RoutingDecision.reason` | No escalation/override/notes/status | Added `is_override`, `escalated`, `notes`; rendered to stderr | `test_override_decision_flags` |
| B1 | Config validation | **Missing** | none | Bad limits/strategy/priority accepted silently | `OrchestrationSettings.validate()` raises `ConfigError` | `test_config_validation_*`, `test_from_config_raises_on_invalid` |
| B2 | Timeout / cancellation honesty | Overclaimed | `future.result(timeout)` | Provider has no cancellation; threads still join | Kept result-timeout for *waiting*; documented that the provider timeout is the real bound; error text says "may still be running" | code comment + VALIDATION report |
| B3 | Failure taxonomy (complete/partial/fallback/failed) | **Missing** | single status | Partial ensemble looked like success | `STATUS_*` + `OrchestrationResult.status` | `test_status_*` (complete/fallback/partial) |
| B4 | Resource-aware concurrency | PARTIAL | `max_parallel_models` cap only | No RAM/VRAM awareness | Conservative configurable cap; uncertainty documented (no reliable VRAM introspection) | n/a (documented BLOCKED detail) |
| B5 | Bounded retries/escalation (no loops) | Present | `max_retries`, single escalation step | — | kept; attempts recorded | `test_run_records_retry_attempts` |
| C1 | Reviewer cannot modify files | Present (by design) | review uses `run_text` (text only) | Not asserted | assert no file writes during review | `test_code_review_reports_non_independence` |
| C2 | Independent review reported | **Missing** | review always ran | Reviewer could equal coder silently | Detect reviewer==coder, print "not independent" note | `test_code_review_*independence*` |
| C3 | Objective verification over votes | PARTIAL | review is advisory; tests run separately (`cle test`/`fix-tests`) | Review doesn't auto-run tests | Review labelled advisory; objective check = tests (documented); ensemble code never decided by vote | n/a |
| E1 | Independent ensemble members | PASS | `_parallel_generate` (separate prompts) | — | — | `test_ensemble_*` |
| E2 | Synthesis notes disagreement, no invented evidence | PASS | synthesis prompt | — | — | live: ensemble flagged disagreement |
| E3 | Ensemble failure policy | **Partial→PASS** | partial handled, status missing | status now distinguishes partial | — | `test_ensemble_tolerates_partial_failure`, `test_status_partial_*` |
| F1 | Observability (durations, retries, status, routing) | Partial | routing line + ok/fail | No timing/attempts/status | Real `duration_s`/`attempts`; status line; routing notes | `test_run_records_retry_attempts`, rendering in `_render_runs` |
| F2 | No fabricated metrics/secrets | PASS | — | — | durations measured (`time.monotonic`); token counts NOT fabricated (provider rarely reports) | — |
| G | Reproducible benchmark (single vs ensemble) | **Missing** | none | — | `scripts/bench_orchestration.py` (mock + --real); results doc | ran mock + bounded real |
| H | Offline compatibility | PASS | stdlib only | — | orchestrator uses only `time`+`concurrent.futures` (stdlib); config shipped in bundle | see VALIDATION report |
| D | Autopilot / full-workflow integration | PARTIAL/BLOCKED | ask/code/debug integrated | autopilot & embeddings not orchestrated | documented policy per command (below); autopilot left on its existing bounded loop | n/a |

## Routing precedence (documented, §3.2)

1. **Explicit `--model` override** → single, **fallback disabled** (unavailable
   override is reported, never silently swapped).
2. **Explicit strategy flag** (`--ensemble`) → ensemble when ≥2 distinct
   generative models exist, else falls through to (4).
3. **Configured strategy** (`orchestration.strategy`): `single` disables
   adaptive escalation.
4. **Adaptive policy**: `priority` (speed→fastest, quality→strongest) or
   complexity escalation (complex→strongest) among configured role models.
5. **Role-based fallback** (legacy `routing.<intent>` → role → model).

## Per-command integration policy (§6.1)

| Command | Orchestration | Notes |
|---|---|---|
| `ask` / `chat` | routing + `--model` + `--ensemble` | stays cheap by default (streams fast role) |
| `explain` | role-based (reasoning) | context-aware; orchestration not forced |
| `code` | `--model`, `--review` | review advisory; objective check = tests |
| `debug` | `--multi-model` (ensemble) | synthesises independent diagnoses |
| `fix-tests` | existing bounded loop | objective verification already (runs tests) |
| `autopilot` | **not integrated (deferred)** | existing bounded plan→edit→test→repair kept; adding ensemble here risks unbounded cost — documented, not faked |
| embeddings | role-based (embedding) | embedding-capability model only; never a chat model |

## Known blockers / limitations

- **No model cancellation** (Ollama): a timed-out request keeps running until the
  provider's own timeout. Documented; not claimed as a hard cancel.
- **No reliable VRAM/context-window introspection**: resource policy is a
  conservative configurable cap, not hardware-measured.
- **`model_calls` metric** is only tracked in mock benchmark mode (the real
  `OllamaProvider` doesn't record calls).
- **Answer quality** is not auto-scored; the benchmark measures objective
  metrics only.
