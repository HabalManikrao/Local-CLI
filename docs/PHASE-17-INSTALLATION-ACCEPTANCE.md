# Phase 17 — Installation Acceptance

Four acceptance levels, strongest the environment allows. Commands and exit
codes are real.

## Environment

- Windows 11, PowerShell, CPU-only (no `nvidia-smi`). Python 3.12.6, Ollama 0.24.0.
- **Live workstation with active network** (required for the session). No
  disposable/disconnected VM available.

## Level 1 — Artifact verification (PASS)

Offline bundle: `dist\CLE-OFFLINE-BUNDLE-0.1.0\verify.ps1`
```
  [OK]   checksum verification: 152 file(s) OK
  Bundle is valid (3 warning(s)).
```
Portable artifact: `dist\CLE-Install.zip` — SHA256 `5EF4C923…`, 0.12 MB, 70 files
(regenerated from source `8cb2c97`).

**Note:** the offline bundle integrity is valid but its CLE content is **stale**
(Phase-13 build). See RELEASE-AUDIT.

## Level 2 — Existing-environment verification (PASS)

CLI smoke tests (real, this environment):

| Command | Result |
|---|---|
| `cle --version` | `cle 0.1.0` |
| `cle --help` | 8+ commands listed |
| `cle config show` | provider + roles + orchestration shown |
| `cle model list` | 4 roles listed |
| `cle doctor` | exit `0` |
| `cle ask "…"` (real local model) | **non-empty response in 7.5 s** — real inference, not just process start (tinyllama; quality is small-model level) |
| `cle code --validate` on seeded defect (Phase 16) | **VALIDATED**, confirmed by independent `pytest` |
| full suite | 210 passed / 2 skipped |

This is an **existing** installation, explicitly **not** a fresh install.

## Level 3 — Clean installation (NOT RUN)

No disposable VM/test machine available; a destructive clean install on the
active workstation is disallowed. The install path is exercised indirectly:
Phase-15 proved `install.ps1` is self-sufficient from an isolated *copy* of the
portable folder (fresh venv, package install, `cle doctor`).

## Level 4 — Genuine offline installation (BLOCKED)

Physical network isolation could not be established on this live workstation.
Per the spec, offline-install acceptance is **BLOCKED** — not claimed from
checksums or an offline banner.

### How to complete Levels 3–4 (future, disposable VM)

1. `Disable-NetAdapter *`; confirm `Test-NetConnection 8.8.8.8` fails.
2. Copy a **freshly rebuilt** bundle; run `verify.ps1`.
3. `setup.ps1 -Offline`; capture exit code.
4. `cle doctor`; run the suite; a real local inference.
5. Re-run setup (idempotency). Record every exit code.

## Gate summary

| Gate | Verdict |
|---|---|
| Artifact verification | PASS |
| Existing-env CLI smoke | PASS |
| Real local inference | PASS |
| Fresh install | NOT RUN (no VM; non-destructive policy) |
| Genuine offline install | **BLOCKED** |
