# INSTALLATION AUDIT — Local CLE

**Date:** 2026-09-03
**Scope:** installation & environment setup only (core CLE unchanged).
**Repo:** `C:\Projects\Local CLI`

---

## 0. Executive summary

CLE's code is complete and offline-first, but bringing a **new Windows machine**
to a working state is currently a ~15-step manual chore (install Python, Git,
ripgrep, Ollama; create a venv; install the package; start the daemon; pull
models; assign roles; index; validate). Nothing about the code needs to change —
we need a **PowerShell-native, idempotent bootstrapper** that automates
detect→install→configure→validate, and that **reuses the existing CLI**
(`cle doctor`, `cle init`, `cle model use`, `cle ask`) rather than duplicating it.

The environment already gives us clean seams to build on: `cle doctor` is a
complete validator, config is layered YAML with a documented override path, and
model roles are set via `cle model use` (never hard-coded in Python).

---

## 1. Current installation process (manual)

From `README.md` / `docs/RUNNING-LOCALLY.md`, a new user must today:

1. Install Python 3.11+, 2. Git, 3. ripgrep, 4. Ollama.
5. `ollama serve`; 6. `ollama pull <fast>`, `<coding>`, `<reasoning>`, `<embed>`.
7. `python -m venv .venv`; 8. activate it; 9. `pip install -e .` (or `.[dev]`).
10. `cle doctor`; 11. `cle init`.
12. `cle model use fast|coding|reasoning|embedding <model>` (×4).
13. `cle index`; 14. (optional) `cle embed`; 15. verify with `cle ask ...`.

No script automates any of this. **No `setup.ps1`/`install.ps1` exists** (only
the venv's own `.venv\Scripts\Activate.ps1`).

---

## 2. Required prerequisites (authoritative sources)

| Prereq | Source of truth | Requirement |
|--------|-----------------|-------------|
| Python | `pyproject.toml` → `requires-python = ">=3.11"` | 3.11+ (3.12 verified) |
| Core deps | `pyproject.toml` → `dependencies` | `typer>=0.12`, `rich>=13.7`, `httpx>=0.27`, `PyYAML>=6.0` |
| Console script | `pyproject.toml` → `[project.scripts]` | `cle = cle.cli.main:app` |
| Ollama | `configs/default.yaml` → `provider` | daemon at `http://127.0.0.1:11434` |
| Git | `configs/default.yaml` → `safety.require_git: true`; `cle doctor` | needed for checkpoints/rollback |
| SQLite | stdlib `sqlite3` | ships with CPython (no install) |

## 3. Optional prerequisites

| Optional | Extra | Effect if absent |
|----------|-------|------------------|
| ripgrep (`rg`) | — | search uses a slower Python fallback (WARN in doctor) |
| FAISS | `.[semantic]` | semantic search still works (pure-Python cosine) |
| tree-sitter | `.[parsing]` | Java parsing uses the built-in heuristic scanner |
| Textual | `.[tui]` | `cle dashboard` uses Rich panels (already fine) |
| pytest | `.[dev]` | needed only to run the test suite |
| NVIDIA GPU | — | CPU inference; **not required** |

## 4–7. Version / Git / Ollama / GPU requirements

- **Python:** `>=3.11`. Do not assume 3.11 exactly — parse and compare.
- **Git:** any recent Git on PATH; do not modify user git config.
- **Ollama:** executable **and** a reachable API on `127.0.0.1:11434`. The
  executable existing is **not** proof the daemon is up — `cle doctor` already
  distinguishes "Ollama (client)" from "Ollama (daemon)". The installer must
  health-check the API, not just `ollama --version`.
- **GPU:** best-effort. `cle doctor`'s GPU check already probes `nvidia-smi` on
  PATH and common Windows locations, and degrades to WARN. Never install drivers.

## 8. Python dependencies

Authoritative in `pyproject.toml` (above). The installer must install from that
file (`pip install -e .` / `.[dev]`) — **no duplicated requirements list.**

## 9. Model requirements

Roles (`configs/default.yaml`): `fast`, `coding`, `reasoning`, `embedding` — all
**empty by default**, assigned via `cle model use <role> <model>` (writes
`.cle/config.yaml`). No model names in Python source. Recommended defaults for
the target hardware (RTX 3060 Ti 8 GB / 32 GB RAM), each fitting VRAM one-at-a-time:

| Role | Default | ~Size |
|------|---------|-------|
| fast | `llama3.2` | ~2.0 GB |
| coding | `qwen2.5-coder:7b` | ~4.7 GB |
| reasoning | `qwen2.5:7b` | ~4.7 GB |
| embedding | `nomic-embed-text` | ~0.3 GB |

Total ~12 GB download. `-SkipModels` must bypass all pulls. The installer keeps
these defaults in **one place** (the installer), applied via the CLI.

## 10. Environment variables

None required — CLE is config-file driven. The installer sets none globally; it
only refreshes the **process** PATH after installing tools.

## 11. Existing setup scripts

None (audited: no `*.ps1`/`*.cmd`/`*.bat`/`*.sh` beyond venv activation).

## 12. Problems with the current setup

1. ~15 manual steps; high drop-off for new users.
2. Easy to conflate "Ollama installed" with "daemon reachable".
3. Model download sizes not surfaced; risk of pulling oversized models.
4. PowerShell execution-policy friction blocks venv activation.
5. No idempotent re-run / repair / verify path.
6. No automated **real** model smoke test (most tests are daemon-free).
7. The Microsoft Store **python.exe alias** in `WindowsApps` can shadow a real
   Python and silently do nothing — detection must guard against it.

## 13. Proposed automated setup architecture

`setup.ps1` — a single PowerShell-native orchestrator (PS 5.1 compatible) plus a
reusable module `scripts/CleSetup.psm1` holding the **pure** functions
(detection/parsing/logging) so they are unit-testable without touching the system.

Phases (each idempotent, detect-before-install):

```
0 Preflight (PS version, repo root, admin state, logging)
1 Detect prerequisites (Python, Git, ripgrep, Ollama, GPU)
2 Install missing prerequisites via winget (official source)
3 Python venv (.venv) — create if absent
4 Dependencies — python -m pip install -e ".[dev]"
5 Ollama — ensure daemon running; poll API health
6 Models — pull recommended (unless -SkipModels); skip existing
7 CLE config — cle init; cle model use <role> <model> (reuse CLI)
8 Validate — cle doctor (fail on critical)
9 Test suite — python -m pytest (fail on failure)
10 Real Ollama smoke test — cle ask "...CLE_SETUP_OK..."
11 Final report
```

Installers/tools are obtained via **winget** (present on this machine:
`Python.Python.3.12`, `Git.Git`, `BurntSushi.ripgrep.MSVC`, `Ollama.Ollama`) —
official, signed, no "curl | iex" of random scripts.

Modes: `-NonInteractive`, `-SkipModels`, `-Repair`, `-Verify`, `-Help`.

## 14. Windows-specific considerations

- **PowerShell 5.1** is the baseline (verified). Avoid `&&`/`||`, ternary, `??`,
  null-conditional — all unavailable in 5.1.
- **Execution policy:** run child scripts with `-ExecutionPolicy Bypass` via the
  `setup.cmd` wrapper so users don't have to change machine policy.
- **PATH refresh:** after winget installs, refresh the **process** PATH from
  Machine+User env so freshly installed exes are found without a new shell.
- **Store alias:** prefer the `py` launcher; validate `python --version` output
  against a real version regex; ignore the WindowsApps stub.
- **Paths with spaces / Unicode / long paths:** the repo path contains a space
  (`C:\Projects\Local CLI`) — quote everything, use `$PSScriptRoot`, never assume
  a fixed drive/path.
- **Admin:** not required for per-user winget installs; elevate only if a
  specific install demands it, and explain why.
- **Ollama daemon:** start via `ollama serve` (background process) or the app;
  confirm readiness by polling `GET /api/tags` on the configured host.

## 15. Failure / recovery strategy

- **Detect→install-if-missing→verify** for every prerequisite; **stop on
  critical failure** with a specific reason + exact manual remedy + rerun hint
  (`.\setup.ps1 -Repair`).
- **Idempotent:** existing venv/deps/models/config are detected and skipped.
- **`-Repair`:** recreate a missing venv, reinstall deps, start a stopped daemon,
  pull missing configured models, re-run doctor + smoke; never wipe working config.
- **`-Verify`:** read-only checks; non-zero exit on any critical failure (CI-friendly).
- **Logging:** every run appends to `logs/setup-YYYYMMDD-HHMMSS.log` (no secrets).
- **Non-critical** items (ripgrep, GPU) → WARN, never block completion.

---

## 16. Reuse decisions (no duplication)

| Concern | Reuse (don't rebuild) |
|---------|------------------------|
| Environment validation | `cle doctor` |
| Project init | `cle init` |
| Model role config | `cle model use` (writes `.cle/config.yaml`) |
| Dependency list | `pyproject.toml` (install via pip) |
| Provider host | `configs/default.yaml` `provider.host` (parsed for health checks) |
| Smoke test | `cle ask` against the real daemon |

The installer adds orchestration + prerequisite installation + a **real** smoke
test; it does not re-implement any CLE logic. **No core architecture changes.**
