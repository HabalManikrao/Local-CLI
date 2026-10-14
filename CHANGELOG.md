# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
