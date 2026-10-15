# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Engineering evaluation + release readiness — Phase 16
- `scripts/bench_engineering.py`: a reproducible, offline (no-LLM) benchmark of
  objective capability — symbol lookup and exact retrieval against ground truth
  established from the real source. Measured: symbol lookup **10/10 (100%)**,
  exact-retrieval **recall 1.00**.
- Controlled real-model evaluation of `cle code --validate` on a disposable
  seeded-defect fixture: CLE diagnosed the bug, modified only the target file
  through the guarded path, ran objective tests, and reported **VALIDATED**
  (confirmed by an independent test run).
- Multi-model cost quantified (ensemble 7–17× single-model latency; quality gain
  unproven on this small sample) → single-model stays the default; ensemble/review
  remain opt-in.
- Release recommendation: **READY WITH KNOWN LIMITATIONS** (docs/PHASE-16-*).
  No tag/release created (requires explicit authorization).

### Validated coding workflow + telemetry — Phase 15
- **`cle code --validate`**: after applying a change, run the project's tests
  (through the existing guarded `TestAgent`) against the **applied** change and
  report an explicit status — `VALIDATED` / `VALIDATION_FAILED` (exit 1) /
  `VALIDATION_SKIPPED` (no test suite). Failing tests are never reported as
  success. `--review` stays advisory (a model opinion; does not run tests); every
  `cle code` run now prints an explicit lifecycle `Status`.
- **Telemetry**: `OrchestrationResult.telemetry()` aggregates model_calls,
  members, successes/failures, retries, and wall-clock vs sum-of-model durations —
  accurate for the **real** provider (not mock-only). Ensemble synthesis is
  tracked as a labelled run, never counted as an ensemble member. The benchmark
  harness now uses this.
- **Autopilot** multi-model integration remains deferred (documented boundaries +
  readiness gates in `docs/PHASE-15-AUTOPILOT-READINESS.md`).
- **Offline**: bundle integrity re-verified (152/152 checksums OK); genuine
  network-isolated acceptance marked BLOCKED (no disconnected machine available).
- +5 tests (205 → 210). Docs: `docs/PHASE-15-*.md`.

### Multi-model orchestration — Phase 14 hardening
- **Correctness/safety:** an explicit `--model` override no longer silently
  falls back to a different model (it reports the failure); orchestration config
  is validated (bad strategy/priority/limits raise an actionable `ConfigError`);
  a result-status taxonomy (`complete_success` / `partial_success` /
  `fallback_success`) means a partial ensemble is never reported as a full
  success; code review now reports whether it was **independent** (a different
  model from the coder) and that it is advisory (objective check = tests).
- **Observability:** per-model measured duration + retry attempts, and an overall
  status line (no fabricated token/confidence values); richer routing notes.
- **Honesty:** documented that a timed-out provider call is not actually
  cancelled (Ollama has no cancellation); the provider timeout is the real bound.
- **Benchmark:** new `scripts/bench_orchestration.py` (mock = offline/deterministic,
  `--real` = installed Ollama). Real run showed ensemble 7–17× slower than single
  and correct `partial_success` on a real member failure.
- +12 tests (193 → 205). Docs: `docs/PHASE-14-{GAP-ANALYSIS,VALIDATION-REPORT,BENCHMARK-RESULTS}.md`.

### Dynamic multi-model orchestration
- New `cle/models/orchestrator.py`: an adaptive engine on top of the existing
  provider/router/registry seams. It chooses *which* model(s) handle a task and
  *how* — **single** (default, legacy behaviour preserved), **ensemble**
  (several models answer, a synthesiser reconciles them + flags disagreement),
  **sequential review** (one model produces, another reviews a diff), with
  availability-aware **fallback**, bounded **retries**, parallel execution, and
  a routing decision that explains *why* a model was picked (observability).
- Capabilities are discovered from role assignments (no hard-coded model names);
  speed tiers from the provider's reported parameter size.
- Config: new `orchestration:` block in `configs/default.yaml` (enabled,
  strategy, limits, routing/escalation, collaboration, ensemble, preferences,
  fallback) — all optional with safe defaults.
- CLI: `cle ask --ensemble` / `--model`, `cle code --review` / `--model`,
  `cle debug --multi-model`, and `cle config show`. Existing commands behave
  exactly as before unless a flag is passed; `--model` always overrides routing.
- +17 tests (routing, escalation, ensemble synthesis, partial failure, fallback,
  retries, config defaults, CLI overrides). Verified live: a real 2-model
  ensemble (tinyllama + qwen3:1.7b) synthesised an answer and noted disagreement.


Hardening pass after validating the agent end-to-end against a real Ollama
daemon (the test suite is fully mocked, so these only surfaced live).

### Added
- GitHub Actions CI (`.github/workflows/ci.yml`): ruff + mypy once on Linux,
  pytest across Linux+Windows × Python 3.11/3.12.
- `ruff` and `mypy` configuration (`pyproject.toml`), added to the `[dev]` extra.
- `cle embed` now shows a progress bar for long runs.
- Opt-in live-daemon smoke test (`tests/e2e/test_live_smoke.py`, `CLE_LIVE_TESTS=1`).
- `cle/py.typed` marker so the package ships its type information.
- Regression/coverage tests: rollback branches, `DebugAgent.diagnose`, the
  Python search fallback, test-runner error paths, `cmd_chat`, context-budget
  truncation, and the fixes below. Suite: 148 → 173 (+2 skipped live).

### Changed
- Default `provider.timeout_seconds` 120 → 300 (context-heavy commands on CPU
  routinely exceed 120s); runtime fallback aligned to match.
- Ollama requests now send an explicit `num_ctx` (default 8192) so large prompts
  are not silently truncated at Ollama's 2048-token default.
- `cle embed` commits each file's vectors in its own transaction and embeds
  outside the DB lock (was one lock held across the whole run).
- Package version is single-sourced from `cle.__version__` via dynamic metadata.
- Removed the unused `semantic`/`parsing`/`tui` extras — FAISS/tree-sitter/Textual
  are not imported; the pure-Python cosine index, heuristic Java scanner and Rich
  dashboard are the real implementations.

### Fixed
- Windows console crash (`UnicodeEncodeError`) on non-cp1252 glyphs and model
  output — stdout/stderr are forced to UTF-8.
- `cle code`/`autopilot`/`fix-tests` crash (`MarkupError`) when model text
  contained `[/...]`; plan output is now escaped.
- Agent plan parsing: non-list `changes`, non-dict change entries, and string
  `at_line`/`risks`/`tests_to_run` are coerced or rejected with a clear error
  instead of raising `AttributeError`/`TypeError`.
- `cle chat`: non-JSON stream lines are skipped, and streaming HTTP errors are
  read before `.text` (no more `ResponseNotRead`).
- Semantic search fails loudly when the configured embedding model differs from
  the one the index was built with (was silently all-zero similarity).
- Any unexpected command error is wrapped in a structured message instead of a
  raw traceback; Ctrl-C exits cleanly.
