# Local CLE — Local CLI Engineering

An **offline-first, Ollama-powered local software engineering agent**. CLE
understands your codebase before acting, uses the appropriate local model for
each task, makes controlled changes, verifies them through tests, and keeps an
auditable trail — all on your machine, no cloud required.

> Status: **all milestones (0–12) implemented**. See
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the big picture and
> [`docs/ARCHITECTURE-AUDIT.md`](docs/ARCHITECTURE-AUDIT.md) for the original
> audit.
>
> **New here?** Follow [`docs/RUNNING-LOCALLY.md`](docs/RUNNING-LOCALLY.md) for a
> complete, offline, step-by-step local setup.

## Install — one command (Windows)

```powershell
.\setup.ps1
```

`setup.ps1` detects, installs (via winget), configures, and validates
everything — Python, Git, ripgrep, Ollama, the virtualenv, dependencies, local
models, model roles — then runs `cle doctor`, the test suite, and a real Ollama
smoke test. It's idempotent (safe to re-run) with `-Repair` and `-Verify` modes.
If PowerShell blocks scripts, use `setup.cmd`. Full guide:
[`docs/INSTALLATION.md`](docs/INSTALLATION.md) ·
troubleshooting: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

```powershell
.\setup.ps1 -Verify        # read-only health check (CI-friendly)
.\setup.ps1 -Repair        # fix only what's broken
.\setup.ps1 -SkipModels    # skip model downloads
```

Requirements: Windows 10/11 + PowerShell 5.1+, winget for auto-install, internet
for the first run (CLE runs offline afterward). NVIDIA GPU optional (CPU works).

### Completely offline (air-gapped) install

Prepare a bundle on an internet PC, copy it via USB, install with no internet:

```powershell
# online PC (models pulled in Ollama first):
.\build-offline-bundle.ps1
# -> copy dist\CLE-OFFLINE-BUNDLE-<ver> to the offline PC, then there:
.\verify.ps1            # optional integrity check
.\setup.ps1 -Offline    # installs Python/Git/Ollama, deps, models — no network
```

Full guide: [`docs/OFFLINE-INSTALLATION.md`](docs/OFFLINE-INSTALLATION.md).

<details>
<summary>Manual install (or macOS/Linux)</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cle doctor                       # validate your environment
cle init                         # initialize a CLE project (creates .cle/)
ollama pull llama3.2             # pull any model you like
cle model use fast llama3.2      # assign it to the 'fast' role
cle models                       # list roles + installed models
cle ask "Explain this project"   # one-shot question
```

See [`docs/RUNNING-LOCALLY.md`](docs/RUNNING-LOCALLY.md) for the full manual walkthrough.
</details>

## Commands

**Setup & info**

| Command | Purpose |
|---|---|
| `cle init` | Initialize a CLE project in the current directory |
| `cle doctor` | Validate Python, Git, ripgrep, SQLite, Ollama, GPU, models, project |
| `cle status` / `cle dashboard` | Project/provider/model/index status (dashboard = panel view) |
| `cle models` · `cle model use <role> <model>` | List / assign models to roles |

**Understand the code**

| Command | Purpose |
|---|---|
| `cle index` | Build the local code index (files/symbols/imports) |
| `cle search "<pat>"` (`-i` `-F`) | Exact search (ripgrep) |
| `cle symbol <name>` | Structural lookup by symbol name |
| `cle explain <file>` | Explain a file (reasoning model + symbol outline) |
| `cle embed` | Build the semantic index (needs an embedding model) |
| `cle ask "<q>"` · `cle chat` | One-shot / interactive chat |

**Memory**

| Command | Purpose |
|---|---|
| `cle memory` · `memory show [kind]` · `memory add` · `memory set` · `memory clear` | Project-scoped memory |

**Change, test, debug (safe)**

| Command | Purpose |
|---|---|
| `cle code "<request>"` | Plan → preview diff → approve → apply |
| `cle diff` · `cle checkpoint` · `cle rollback` | Git safety |
| `cle test` · `cle debug` · `cle fix-tests` | Run/diagnose/auto-fix tests (bounded) |
| `cle autopilot "<task>"` | Autonomous plan→edit→test→repair (bounded) |

**Java / Winium & benchmarking**

| Command | Purpose |
|---|---|
| `cle java analyze` · `cle winium analyze` | Evidence-backed static findings (no changes) |
| `cle benchmark` | Benchmark models/agents on local tasks; store results |

## Configuration

Defaults live in [`configs/default.yaml`](configs/default.yaml). Project
overrides go in `.cle/config.yaml` (created by `cle init`) and are deep-merged
over the defaults. No model names are hard-coded — roles are assigned via
`cle model use`.

## Development

```powershell
pytest                # run the full suite (offline; no daemon needed)
pytest tests/unit     # unit tests only
```

Architecture and design docs live under [`docs/`](docs/).
