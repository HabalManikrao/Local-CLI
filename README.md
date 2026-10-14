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

Prefer a lean, no-frills install? `install.ps1` does just the essentials —
install prerequisites (skipping any already present), set up the package, pull
only the missing models, and assign roles — without the test-suite / smoke-test /
offline-bundle machinery:

```powershell
.\install.ps1                 # interactive
.\install.ps1 -NonInteractive # unattended (auto-yes) for a fresh machine
.\install.ps1 -SkipModels     # prerequisites + package only
```

Requirements: Windows 10/11 + PowerShell 5.1+, winget for auto-install, internet
for the first run (CLE runs offline afterward). NVIDIA GPU optional (CPU works).

### Set up a brand-new Windows machine (from scratch)

Nothing installed yet? Full procedure:

**1. Get the code onto the machine.**
- Download the ZIP: on GitHub, **Code ▸ Download ZIP**, then extract (e.g. to
  `C:\Local-CLI`). *(Or, if Git is already present:
  `git clone https://github.com/HabalManikrao/Local-CLI.git C:\Local-CLI`.)*

**2. Open PowerShell as Administrator.** Start menu → type **PowerShell** →
right-click → **Run as administrator**. (Admin lets winget install
Python/Git/Ollama machine-wide.)

**3. Run the installer** from the folder you created:

```powershell
cd "C:\Local-CLI"
powershell -ExecutionPolicy Bypass -File .\install.ps1 -NonInteractive
```

`-ExecutionPolicy Bypass` avoids the "scripts are disabled" block for this run;
`-NonInteractive` makes it fully hands-off. Drop `-NonInteractive` to confirm each
step, or add `-SkipModels` to install everything except the (large) models.

**4. Verify:**

```powershell
.\.venv\Scripts\cle.exe doctor
```

All checks should be green (a GPU warning on a CPU-only machine is fine).

> **Gotchas.** winget ships with Windows 10/11 as the *App Installer* — install it
> from the Microsoft Store if it's missing. The first run needs internet
> (prerequisites + ~11 GB of default models; CLE runs offline afterward). If a
> command isn't found right after its tool was installed, open a **new** terminal
> and re-run — the installer is idempotent and skips whatever is already done.

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

> **New user?** The [**Usage guide**](docs/USAGE.md) walks through real
> workflows (understand code · change safely · fix tests · autopilot) with
> copy-paste commands. The table below is the quick reference.

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
