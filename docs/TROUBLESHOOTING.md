# Troubleshooting

Most problems are reported directly by `setup.ps1` or `cle doctor` with an exact
remedy. This page collects the common ones. Every setup run also writes a log to
`logs\setup-YYYYMMDD-HHMMSS.log`.

## First move for any issue

```powershell
.\setup.ps1 -Verify     # read-only: shows exactly what's broken
.\setup.ps1 -Repair     # fixes venv / deps / daemon / models
```

## Installer (setup.ps1)

| Symptom | Cause / Fix |
|---------|-------------|
| `cannot find scripts\CleSetup.psm1` | Run `setup.ps1` from the repo root (it needs the `scripts\` folder beside it). |
| `winget is not available` | Install **App Installer** from the Microsoft Store, or install Python/Git/Ollama manually, then `.\setup.ps1 -Repair`. |
| `<tool> still not available after install` | winget installed it but PATH isn't refreshed in this shell. Open a **new** terminal and rerun `.\setup.ps1 -Repair`. |
| Script won't run / "running scripts is disabled" | Use `setup.cmd`, or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| A winget install needs elevation | Approve the UAC prompt, or run winget for that package in an elevated terminal, then `-Repair`. |
| Setup stops at a phase | Read the `Action:` block it printed — it names the exact fix and rerun command. |

## Python

| Symptom | Fix |
|---------|-----|
| `No usable Python` though Python "is installed" | You may have the **Microsoft Store alias** (a stub). Install real Python (`winget install --id Python.Python.3.12 -e`) or use the `py` launcher, then `-Repair`. |
| Wrong Python picked | The installer prefers `py -3.12`/`-3.11`. Ensure a 3.11+ interpreter is present; `py --list` shows what's available. |
| `.venv` creation failed | Delete `.venv` and rerun `-Repair`, or create it manually: `py -3.12 -m venv .venv`. |

## Dependencies

| Symptom | Fix |
|---------|-----|
| `pip install failed` | Read the pip output in the log. Retry: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`. Behind a proxy? Configure pip's proxy first. |
| `cle not importable` in `-Verify` | Dependencies aren't installed — run `.\setup.ps1 -Repair`. |

## Ollama

| Symptom | Fix |
|---------|-----|
| `Ollama daemon not reachable` | Start it: `ollama serve` (or launch the Ollama app), then `-Repair`. |
| API didn't come up within timeout | Ensure nothing else is bound to port 11434; check the Ollama app is running; rerun `-Repair`. |
| `ollama list` hangs | The daemon is down — the installer avoids this by health-checking first; if you hit it manually, start the daemon. |
| Model pull is slow / stalls | Large models are big downloads; retry `ollama pull <model>`. Corporate networks may throttle or block the Ollama registry — pull on a permitted network. |
| `Ollama model 'X' is unavailable` | `ollama list` to see installed names (they include a tag, e.g. `qwen2.5:7b`); `ollama pull X`. |

## Models & roles

| Symptom | Fix |
|---------|-----|
| A role shows "not installed; not assigned" | Pull the model (`ollama pull <model>`) then `-Repair`, or assign a model you already have: `cle model use <role> <model>`. |
| Model too slow / out of memory | Use a smaller model for that role (e.g. a 3B for `coding`) or a quantized tag; an 8 GB GPU runs ~3B–8B comfortably. |
| Want different models than the defaults | `cle model use <role> <model>` — no re-setup needed. |

## Validation

| Symptom | Fix |
|---------|-----|
| `cle doctor` reports a FAIL | Address the single FAIL item it prints (usually the daemon or a model), then `-Repair`. WARNs (ripgrep, GPU) are non-fatal. |
| Test suite failed | Run it directly: `.\.venv\Scripts\python.exe -m pytest`. Inspect the failing test; the core suite is fully offline. |
| Real Ollama smoke test failed | Try manually: `.\.venv\Scripts\cle.exe ask "Reply with exactly: CLE_SETUP_OK"`. Confirm a `fast` model is configured and the daemon is up. |

## GPU (optional)

| Symptom | Fix |
|---------|-----|
| `NVIDIA GPU not detected` | Informational only — CLE runs on CPU. If you have an NVIDIA card, install its driver so `nvidia-smi` is available. The installer never installs GPU drivers. |

## Windows specifics

- **Paths with spaces / Unicode** are handled; always run from the repo root.
- **PATH after installs**: the installer refreshes the process PATH, but if a
  tool still isn't found, open a new terminal and rerun `-Repair`.

Still stuck? Check the newest file in `logs\`, and the design docs
[`INSTALLATION.md`](INSTALLATION.md) / [`INSTALLATION-AUDIT.md`](INSTALLATION-AUDIT.md).
