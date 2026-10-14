# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Local CLE (Local CLI Engineering)** — an offline-first, Ollama-powered local
software engineering agent. A single Python 3.11+ package (`cle/`), Windows-first.
Stack: `typer` + `rich` + `httpx` + `PyYAML`, SQLite for index/memory, ripgrep for
search (pure-Python fallback when `rg` is absent). Semantic search uses a
pure-Python cosine index and Java parsing a heuristic scanner — FAISS/tree-sitter
are possible future accelerations, not currently wired in.

## Commands

Development uses the project-root virtualenv (`.venv`). Either activate it or call
its interpreter directly: `.\.venv\Scripts\python.exe -m pytest`.

```powershell
pytest                        # full suite — fully offline, no Ollama daemon needed
pytest tests/unit             # fast unit tests
pytest -m integration         # temp git repos, sqlite, ripgrep
pytest -m e2e                 # CLI + real pytest subprocess (coding/fix-tests/autopilot)
pytest tests/unit/test_x.py::test_name   # a single test
pip install -e ".[dev]"       # install with dev deps (pytest, ruff, mypy)
ruff check .                  # lint   (config in pyproject.toml [tool.ruff])
mypy                          # type-check the cle package
```

CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on push/PR (lint once on
Linux; tests across Linux+Windows × Py 3.11/3.12). The app runs via the `cle` console
script (e.g. `cle doctor`, `cle index`, `cle ask "..."`); see README.md for the full
command catalog.

## Architecture — the big picture

Strictly downward-pointing layers (`cle/cli` → agents/analysis → context → indexing
→ models → Ollama), with cross-cutting `tools`, `safety`, `memory`, `evidence`. Full
diagram and layer table in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Four enforced choke points — do not bypass these seams:**

- **`cle/models/base.py::ModelProvider`** — the *only* path that talks to an LLM
  (`OllamaProvider` today). New providers implement this interface; callers never change.
- **`cle/models/router.py` + `registry.py`** — intent → role → model. **No model names
  are ever hard-coded**; roles (`fast`, `reasoning`, `embedding`, …) are configured via
  `cle model use` and resolved at runtime.
- **`cle/safety/permissions.py::PermissionGuard` + `cle/tools/filesystem.py`** — the
  *only* path to writes / shell / git mutation. Agents and LLMs never act on the
  filesystem directly; they go through the guarded `FileSystem`.
- **`cle/evidence.py::EvidenceSource`** — `LOCAL | CACHED | LIVE`, and a source is
  **never upgraded to LIVE**. Preserve this when handling retrieved context/claims.

**Agents** (`cle/agents/`: coding, testing, debugging) all follow a
plan → preview diff → approve → guarded-apply loop. Add a new one by subclassing
`agents.base.BaseAgent` and reusing the context engine + edit/permission tools.

## Conventions

- **Errors** are `CleError` subclasses (`cle/errors.py`) carrying an actionable
  `remedy`. Never raise a bare error — Typer wiring in `cle/cli/main.py` catches
  `CleError` centrally and prints the remedy.
- **CLI commands** live in `cle/cli/commands.py` as functions returning an exit code;
  `cle/cli/main.py` is the thin Typer wiring layer.
- **Model/LLM output** is printed with `markup=False` (its brackets are not Rich markup).
- **Tests are fully offline**: LLM I/O is faked via `tests/conftest.py::FakeProvider`
  or mocked with `httpx.MockTransport`. Keep new tests daemon-free.
- Prefer stdlib + the small dependency set; justify any new dependency and keep the
  core runnable offline. Use `pathlib` + UTF-8; drive git/processes via `subprocess`.

## Config & data

- Defaults ship in [`configs/default.yaml`](configs/default.yaml). Project overrides
  go in `.cle/config.yaml` (created by `cle init`) and are **deep-merged** over defaults.
- Per-project state lives under `<project>/.cle/` (index/memory/checkpoints as SQLite +
  JSON) and the audit trail under `<project>/logs/<date>/`.

## Environment notes

Ollama is installed but the daemon is usually not running and no models are pulled;
`nvidia-smi` may not be on PATH (RTX 3060 Ti). `cle doctor` reports all of this. None
of it blocks the test suite, which is entirely offline.
