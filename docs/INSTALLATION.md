# Installation — one command

Local CLE ships an automated Windows bootstrapper. From a fresh clone:

```powershell
.\setup.ps1
```

That's it. `setup.ps1` detects, installs, configures, and validates everything —
you don't install prerequisites by hand.

If PowerShell blocks scripts, use the wrapper (bypasses policy just for this run):

```cmd
setup.cmd
```

---

## What it does

```
Preflight  ->  Prerequisites  ->  Virtualenv  ->  Dependencies  ->  Ollama daemon
   ->  Models  ->  CLE config  ->  cle doctor  ->  test suite  ->  real Ollama smoke test
   ->  final report
```

- **Detects before installing** and is **idempotent** — safe to run repeatedly.
- **Installs missing prerequisites** via **winget** (official sources):
  Python 3.12, Git, ripgrep, Ollama.
- Creates `.venv` and installs CLE + dependencies from `pyproject.toml`.
- Starts the **Ollama daemon** and waits for its API.
- Pulls recommended local models (sized for an RTX 3060 Ti / 32 GB) and assigns
  them to CLE's `fast` / `coding` / `reasoning` / `embedding` roles via
  `cle model use`.
- Validates with **`cle doctor`**, runs the **full test suite**, and performs a
  **real** model smoke test (`cle ask` -> expects `CLE_SETUP_OK`).
- Writes a log to `logs\setup-YYYYMMDD-HHMMSS.log`.

## Requirements

- Windows 10/11, **Windows PowerShell 5.1+** (built in) or PowerShell 7.
- **winget** (App Installer) for automatic prerequisite installs. Without it,
  the script tells you exactly what to install manually.
- Internet access for the first run (to install tools + pull models). CLE runs
  **offline** afterward.
- An NVIDIA GPU is optional — CLE runs on CPU if absent.

## Options

```powershell
.\setup.ps1                 # full setup (interactive)
.\setup.ps1 -NonInteractive # use defaults, never prompt
.\setup.ps1 -SkipModels     # don't pull / configure models
.\setup.ps1 -Repair         # fix only what's broken (venv, deps, daemon, models)
.\setup.ps1 -Verify         # read-only checks; non-zero exit on failure (CI)
.\setup.ps1 -Help           # usage
```

### Recommended models (defaults)

| Role | Model | ~Size |
|------|-------|-------|
| fast | `llama3.2` | 2.0 GB |
| coding | `qwen2.5-coder:7b` | 4.7 GB |
| reasoning | `qwen2.5:7b` | 4.7 GB |
| embedding | `nomic-embed-text` | 0.3 GB |

Only missing models are downloaded. Change any role later without re-running
setup:

```powershell
.\.venv\Scripts\cle.exe model use coding <your-model>
```

## After setup

```powershell
.\.venv\Scripts\cle.exe ask "Explain this project"
.\.venv\Scripts\cle.exe index
.\.venv\Scripts\cle.exe winium analyze
.\.venv\Scripts\cle.exe autopilot "..."
```

(Or activate the venv — `.\.venv\Scripts\Activate.ps1` — and just type `cle ...`.)

## Verifying an existing install

```powershell
.\setup.ps1 -Verify
```

Prints a pass/fail table across every prerequisite and check, and returns a
non-zero exit code if anything critical is broken — handy for CI or triage.

## Repairing

```powershell
.\setup.ps1 -Repair
```

Recreates a missing/broken `.venv`, reinstalls dependencies, starts a stopped
Ollama daemon, pulls any missing configured models, and re-validates — without
touching working configuration.

## Design & internals

- Orchestrator: [`setup.ps1`](../setup.ps1). Reusable functions:
  [`scripts/CleSetup.psm1`](../scripts/CleSetup.psm1).
- Tests: [`tests/setup/Run-SetupTests.ps1`](../tests/setup/Run-SetupTests.ps1)
  (no dependencies) and `tests/setup/CleSetup.Tests.ps1` (Pester).
- The installer **reuses the CLE CLI** (`cle doctor/init/model use/ask`) and the
  authoritative `pyproject.toml` / `configs/default.yaml`; it does not duplicate
  CLE logic. See [`INSTALLATION-AUDIT.md`](INSTALLATION-AUDIT.md).

Trouble? See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
