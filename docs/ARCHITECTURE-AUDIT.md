# ARCHITECTURE AUDIT — Local CLI Engineering (CLE)

**Date:** 2026-09-02
**Auditor:** Lead Architect (Milestone 0)
**Repository:** `C:\Projects\Local CLI`
**Status:** Greenfield — audit complete, ready for Milestone 1.

---

## 0. Executive Summary

This is a **greenfield repository**. The working directory contains no source
code, no build system, no tests, no configuration, and is **not yet a git
repository**. The only pre-existing artifact is `.claude/settings.local.json`
(a Claude Code permission stub), which is unrelated to the product.

Because there is nothing to reuse, extend, or replace, the
`REUSE > EXTEND > REFACTOR > REPLACE` rule collapses to: **build new, cleanly,
per the target architecture in the master prompt.** There is no legacy
architecture to preserve and no risk of overwriting user work inside this repo.

The **primary risk is not the codebase — it is the environment.** Ollama is
installed but not running, no models are pulled, no NVIDIA GPU is visible on
`PATH`, and no vector/parser libraries are installed. `cle doctor` (Milestone 1)
must diagnose exactly these conditions and tell the user how to fix each one.

---

## 1. Current Architecture

**None.** The repository is empty except for:

```
C:\Projects\Local CLI\
└── .claude\
    └── settings.local.json   # Claude Code permission stub (allows one echo cmd)
```

- No `pyproject.toml`, `setup.py`, or `requirements.txt`.
- No Python package, module, or script.
- No CLI, agent, model, index, memory, or tool code.
- No SQLite database or schema.
- No `docs/` (this file creates it).
- No git history (`git status` → *fatal: not a git repository*).

---

## 2. Environment Assessment

Verified on the target machine during this audit:

| Component     | Status                | Detail                                                        |
|---------------|-----------------------|---------------------------------------------------------------|
| Python        | ✅ OK                 | 3.12.6 (satisfies the 3.11+ requirement)                      |
| pip           | ✅ OK                 | 26.2.1                                                         |
| Git           | ✅ OK                 | 2.52.0.windows.1                                              |
| ripgrep (`rg`)| ✅ OK                 | 14.1.1 on `PATH`                                             |
| Ollama client | ⚠️ Installed, not running | client 0.24.0; **"could not connect to a running instance"** |
| Ollama models | ❓ Unknown            | Cannot list until the daemon runs                            |
| NVIDIA GPU    | ⚠️ Not on `PATH`     | `nvidia-smi` not found via `PATH` (RTX 3060 Ti expected)     |
| FAISS         | ❌ Missing            | `import faiss` fails                                          |
| tree-sitter   | ❌ Missing            | `import tree_sitter` fails                                    |
| SQLite        | ✅ OK (implied)       | Ships with CPython `sqlite3`                                 |

**Implications:**

1. `cle doctor` must treat "Ollama installed but daemon down" as a distinct,
   actionable state (tell the user to run `ollama serve` / start the app).
2. GPU detection must not rely solely on `nvidia-smi` being on `PATH`. On
   Windows it commonly lives at
   `C:\Windows\System32\nvidia-smi.exe` or under the driver store. Doctor should
   probe known locations and degrade gracefully to "GPU: unknown" rather than
   error.
3. FAISS and tree-sitter are optional-at-first: the system must **function
   without them** (exact + structural search work with ripgrep alone) and only
   light up semantic search / precise Java parsing when they are installed. This
   preserves the offline + incremental-milestone requirements.

---

## 3. Existing Reusable Components

None within the repo. External tools already present that we will *drive*
(not vendor):

- **ripgrep** — exact/text search backend (Milestone 5).
- **git CLI** — checkpoints, diff, rollback, state checks (Milestone 8).
- **Ollama** — model provider once running (Milestone 2).
- **CPython stdlib** — `sqlite3` (memory/index), `subprocess`, `pathlib`,
  `logging`, `tomllib`.

---

## 4. Problems Discovered

1. **Not a git repository.** Milestone 8 (checkpoints/rollback) and the
   `require_git: true` safety default depend on git. We must `git init` early
   and make git-awareness a first-class, testable concern.
2. **Ollama daemon offline.** Every LLM path fails until it runs. The provider
   layer (Milestone 2) must return *structured, actionable* errors, and doctor
   must catch this before the user hits a cryptic failure.
3. **No models pulled.** Model roles must be *config-driven and unset-tolerant*:
   the router must clearly report "no model configured for role X" instead of
   crashing (Milestone 3).
4. **GPU invisible on PATH.** Hardware-aware routing (RTX 3060 Ti, 8 GB VRAM)
   needs a robust detector; treat GPU info as best-effort.
5. **Optional native deps missing** (FAISS, tree-sitter). Must be graceful
   degradations, never hard requirements for core commands.

---

## 5. Proposed Architecture

Adopt the master-prompt target architecture verbatim, with a Windows-first,
degrade-gracefully posture. Package root `cle/` with layered dependencies
pointing **downward only**:

```
cli ──▶ core (orchestrator/planner/task/permissions)
core ──▶ agents ──▶ tools + context + models
context ──▶ indexing + models(embeddings)
everything ──▶ config + logging + safety(audit)
models ──▶ provider(Ollama)   # single choke point for all LLM I/O
```

**Non-negotiable seams (established now, even if thinly implemented):**

- **`ModelProvider` interface** — the *only* place that talks to Ollama.
  `health/list_models/generate/chat/stream/embed`. Future online providers
  implement the same interface (Milestone 2, §11 offline rule).
- **`ModelRouter`** — maps task *roles* (FAST/CODING/REASONING/EMBEDDING) to
  configured model names; never hard-codes model names (Milestone 3, §20).
- **Tool + Permission layer** — the *only* path to filesystem writes, shell,
  and git mutations. LLMs never execute shell directly (§8).
- **Evidence tagging** — `LOCAL | CACHED | LIVE` classification carried through
  context/research; never upgrade LOCAL/CACHED → LIVE (§10).
- **Audit log** — every tool execution recorded under `logs/<date>/…` (§9).

---

## 6. Components to Reuse / Extend / Replace

| Action  | Component                                                       |
|---------|----------------------------------------------------------------|
| REUSE   | ripgrep, git CLI, Ollama, Python stdlib (`sqlite3`, `subprocess`, `logging`, `tomllib`) |
| EXTEND  | — (nothing internal to extend yet)                             |
| REPLACE | — (nothing to replace)                                         |
| CREATE  | All `cle/` package code, config schema, tests, docs           |

No replacement justifications are required because there is no existing
implementation.

---

## 7. Dependency Decisions

Minimize dependencies; keep everything installable offline afterward.

**Core (Milestone 1):**
- `rich` — terminal rendering (tables, panels, diffs).
- `typer` *or* stdlib `argparse` — CLI. **Decision: `typer`** (thin over
  `click`, ergonomic subcommands, good help/errors) unless the user prefers
  zero non-stdlib CLI deps.
- `PyYAML` — YAML config (`configs/default.yaml`). TOML via stdlib `tomllib`
  for `pyproject`.
- `httpx` — Ollama HTTP calls (timeouts, streaming). Alternative: stdlib
  `urllib`. **Decision: `httpx`** for clean timeout/stream ergonomics.
- `pytest` — tests.

**Deferred / optional (light up when needed, never block core):**
- `tree-sitter` + `tree-sitter-java` — precise structural parsing (M4/M10).
  Fallback: regex/heuristic extraction when absent.
- `faiss-cpu` (or `numpy`-only cosine index) — semantic search (M5).
  Fallback: exact + structural search only.
- `textual` — TUI (M12), optional.
- `GitPython` — **not** adopted; git CLI via `subprocess` is lighter and
  matches the "drive existing tools" posture. Revisit only if CLI parsing
  becomes painful.

Every optional dependency is gated behind a capability check surfaced by
`cle doctor`.

---

## 8. Risks

| Risk                                             | Severity | Mitigation                                                                 |
|--------------------------------------------------|----------|----------------------------------------------------------------------------|
| Ollama daemon down / models absent               | High     | Structured provider errors; doctor pre-flight; router reports unset roles  |
| GPU not detectable → wrong model sizing          | Medium   | Best-effort detector (probe known paths); conservative defaults for 8 GB   |
| Windows path/encoding/subprocess quirks          | Medium   | `pathlib` everywhere; `encoding='utf-8'`; no shell-string interpolation    |
| Semantic search deps heavy / unavailable offline | Medium   | Graceful degradation; FAISS optional; pin CPU wheels                       |
| Autonomous mode looping / destructive edits      | High     | `max_iterations`, approval gates, git checkpoints, `allow_delete:false`    |
| Scope (12 milestones) vs. incremental safety     | Medium   | Strict per-milestone DoD; run full test suite before advancing            |

---

## 9. Migration Strategy

No migration — greenfield. Bootstrap sequence:

1. `git init` + `.gitignore` (Python, venv, `logs/`, `*.db`, index caches).
2. `pyproject.toml` with pinned core deps and `pytest` config.
3. `cle/` skeleton with the seams from §5 (thin but real).
4. `configs/default.yaml` with safety + model-role placeholders.
5. First commit = working `cle --help` + `cle doctor` + passing tests.

Each subsequent milestone is additive and leaves `cle` runnable and green.

---

## 10. Milestone Implementation Order

Follow the master-prompt order (0 → 12). Dependencies:

```
M1 CLI ─▶ M2 Provider ─▶ M3 Router
                    └─▶ M4 Index ─▶ M5 Context/Retrieval ─▶ M6 Memory
                                                     └─▶ M7 Coding Agent ─▶ M8 Safe Edit/Git
                                                                     └─▶ M9 Test/Debug ─▶ M10 Java/Winium
                                                                                    └─▶ M11 Autopilot ─▶ M12 TUI/Benchmark
```

Gate: no milestone starts until the previous one's full test suite is green.

---

## 11. Testing Strategy

- `tests/unit/` — pure logic: config parsing, router mapping, provider error
  translation, path handling, evidence tagging. No network; Ollama HTTP mocked.
- `tests/integration/` — SQLite index/memory round-trips, ripgrep search,
  git checkpoint/rollback against a temp repo, tool+permission enforcement.
- `tests/e2e/` — CLI invocations via subprocess against a fixture project;
  Ollama stubbed by a fake provider so tests run **fully offline** in CI.
- Determinism: fake `ModelProvider` for anything touching an LLM so the suite
  never requires a running daemon.

---

## 12. Recommendation

Proceed to **Milestone 1 — CLI Foundation**. Establish the package skeleton,
config loading, structured logging, project/git detection, and the six commands
(`init`, `doctor`, `status`, `models`, `ask`, `chat`) — with `doctor` wired to
the environment gaps found above — then lock it in with tests and the first
git commit.
