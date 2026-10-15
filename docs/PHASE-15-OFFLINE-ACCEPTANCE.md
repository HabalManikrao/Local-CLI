# Phase 15 — Offline Acceptance

## Environment & isolation method

- **Machine:** the developer's live Windows 11 workstation.
- **Network:** **active** (required for this working session).
- **Isolation:** a genuinely network-disconnected machine/VM was **not**
  available. Per the Phase-15 spec, physical offline acceptance is therefore
  **BLOCKED** and is not claimed. All *safe local* checks were performed and are
  reported below with real output.

## Bundle under test

- `dist/CLE-OFFLINE-BUNDLE-0.1.0/` (CLE 0.1.0). Note: this bundle predates the
  Phase-14/15 orchestration config; it is used here to validate **bundle
  integrity and the offline workflow**, not feature currency. A rebuild
  (`build-offline-bundle.ps1`) would include the new config. The *portable*
  installer bundle (`dist/CLE-Install/`) was refreshed and does contain the
  `orchestration:` config.

## Integrity verification (actual output)

Command: `dist\CLE-OFFLINE-BUNDLE-0.1.0\verify.ps1`

```
  [OK]   manifest.json (CLE 0.1.0)
  [OK]   checksums/SHA256SUMS.txt (152 entries)
  [OK]   checksum verification: 152 file(s) OK
  [WARN] no python installer bundled (offline machine must already have python)
  [WARN] no git installer bundled (offline machine must already have git)
  [WARN] no ollama installer bundled (offline machine must already have ollama)
  [OK]   python packages: 25 file(s)
  [OK]   model 'tinyllama' (fast): manifest + 5 blob(s)
  [OK]   model 'nomic-embed-text' (embedding): manifest + 4 blob(s)
  Bundle is valid (3 warning(s)).
```

**Result:** manifest present; **SHA256 checksums matched on all 152 files**;
Python wheels (25) present; model artifacts (tinyllama, nomic-embed-text) present
with their blobs. The 3 warnings are by design (prerequisite installers are not
bundled; the offline machine must already have Python/Git/Ollama).

## No-download evidence (dependency path)

- Orchestration (the Phase 14/15 feature work) adds **no third-party dependency**
  — `cle/models/orchestrator.py` imports only stdlib (`time`,
  `concurrent.futures`, `dataclasses`). `pyproject.toml` runtime deps unchanged
  (`typer`, `rich`, `httpx`, `PyYAML`).
- The full automated test suite runs with **no daemon and no network** (providers
  are mocked); the mock benchmark runs fully offline.

## Secrets check

- `grep` of the bundle manifest/scripts shows no API keys, tokens, or credentials
  (CLE is local-only; it has no cloud credentials to leak).

## Gate summary

| Check | Verdict | Evidence |
|---|---|---|
| Bundle verification | **PASS** | verify.ps1 output above |
| Checksums match | **PASS** | 152/152 files OK |
| Model artifacts complete | **PASS** | tinyllama + nomic-embed-text blobs OK |
| Local-only Python deps present | **PASS** | 25 wheels in bundle |
| No accidental secrets | **PASS** | none in a local-only tool |
| Tests run offline | **PARTIAL** | suite is mock-only (no network needed), but not re-run with the NIC disabled |
| **Genuine network isolation** | **BLOCKED** | no disconnected machine available on this live workstation |
| Fresh offline setup (`setup.ps1 -Offline`) | **NOT RUN** | would install Python deps + import models; not run on this already-provisioned machine to avoid mutating it |
| Idempotency / recovery | **NOT RUN** | depends on a disconnected test machine |

## How to complete the BLOCKED gate (future)

On a disposable, network-disconnected Windows VM:
1. Disable the NIC (`Disable-NetAdapter`), confirm `Test-NetConnection` fails.
2. Copy the bundle, run `verify.ps1`, then `setup.ps1 -Offline`.
3. `cle doctor`, run the suite, and a real local inference.
4. Re-run setup for idempotency.
Capture each command's exit code as evidence.
