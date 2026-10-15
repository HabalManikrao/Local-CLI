# CLE 0.1.0 — Release Candidate Manifest

Identifies the exact source and artifacts a reviewer would authorize. **No tag,
publication, or upload has been performed.**

## Source

| Field | Value |
|---|---|
| Target version | `0.1.0` |
| Source commit | `8cb2c97` (branch `master`) |
| Repository | github.com/HabalManikrao/Local-CLI |
| Prepared | Phase 17 (build date recorded by the build tools; not hard-coded here) |

## Build environment

| Field | Value |
|---|---|
| OS | Windows 11 (windows-amd64) |
| Python | 3.12.6 |
| PowerShell | 5.1+ (Windows PowerShell) |
| Ollama | 0.24.0 |
| Runtime deps | `typer>=0.12`, `rich>=13.7`, `httpx>=0.27`, `PyYAML>=6.0` (unchanged) |

## Artifacts

### A. Portable installer (current — matches `8cb2c97`)

| Field | Value |
|---|---|
| Path | `dist/CLE-Install.zip` |
| Build command | `.\package-portable.ps1 -Zip` |
| Size | 0.12 MB (70 files) |
| SHA-256 | `5EF4C9232F020C569FB1F3F81110F5C893ECF0DE4A626FDB7F4708A20CA6F763` |
| Contents | `install.cmd`, `install.ps1`, `test-run.cmd`, `START-HERE.txt`, `cle/` package, `configs/default.yaml` (incl. `orchestration:`), `scripts/CleSetup.psm1`, docs |
| Install | online path — winget installs Python/Git/Ollama, pulls missing models |

### B. Offline bundle (STALE — predates this source)

| Field | Value |
|---|---|
| Path | `dist/CLE-OFFLINE-BUNDLE-0.1.0/` |
| Built | 2026-09-08 (Phase 13) — **does not contain Phases 14–16** |
| Integrity | valid: **152/152** checksums OK (SHA256SUMS.txt) |
| Models bundled | tinyllama (fast), nomic-embed-text (embedding) |
| Python wheels | 25 |
| **Action required** | **rebuild from `8cb2c97`** (`build-offline-bundle.ps1`) before an offline release |

> The `.zip` and offline bundle are git-ignored build artifacts (not committed).
> No artifact URLs exist — nothing has been uploaded.

## Verification results

| Check | Result |
|---|---|
| pytest | 210 passed, 2 skipped |
| ruff | pass |
| mypy | pass (55 files) |
| CLI smoke | pass (version/help/config/model/doctor/ask) |
| Real local inference | pass (7.5 s, tinyllama) |
| Offline bundle checksums | 152/152 |
| Secrets in artifacts | none |

## Platform / model prerequisites

- Windows 10/11 + PowerShell 5.1+, winget (online install), internet for first
  online run. Offline install needs a rebuilt bundle + Python/Git/Ollama already
  present.
- Models: assign via `cle model use <role> <model>` (no model names hard-coded).

## Release recommendation

**READY WITH KNOWN LIMITATIONS — AUTHORIZATION REQUIRED.** The online/portable
path is current and verified; the offline bundle must be rebuilt first. See
RELEASE-NOTES-0.1.0 for limitations.
