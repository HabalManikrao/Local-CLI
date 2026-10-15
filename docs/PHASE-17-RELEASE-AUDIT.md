# Phase 17 — Release Audit

## Repository baseline (verified)

- `master` @ `8cb2c97` (confirmed: `git cat-file -t 8cb2c97` → commit); tree clean, in sync.
- Suite: **210 passed / 2 skipped**; ruff clean; mypy clean (55 files).

## Version consistency (Workstream A)

| Source | Value | Verdict |
|---|---|---|
| `pyproject.toml` | `dynamic = ["version"]` → `attr = "cle.__version__"` | single-sourced |
| `cle.__version__` | `0.1.0` | — |
| Installed package metadata | `0.1.0` | agrees |
| `cle --version` | `cle 0.1.0` | agrees |
| Offline bundle name / manifest | `CLE-OFFLINE-BUNDLE-0.1.0`, `bundle_version=0.1.0`, `cle_version=0.1.0` | agrees |
| README / CHANGELOG | no stray release version strings (CHANGELOG uses `[Unreleased]`) | consistent |

**Verdict: PASS** — the version is single-sourced and consistent everywhere. No
duplication to reconcile. The version has **never been tagged or published**.

### Versioning decision point (for the authorizer)

The `0.1.0` label was already used for the **Phase-13 offline bundle** (built
2026-09-08). The source has since gained Phases 14–16 (orchestration, validated
coding, telemetry, evaluation). So **two different contents share the `0.1.0`
label**. Two clean options — not auto-applied:

1. **Release `0.1.0` from `8cb2c97`** and rebuild the bundle so the `0.1.0`
   artifact matches current source (recommended if `0.1.0` was never released —
   which is the case here).
2. **Bump to `0.2.0`** to distinguish from the older `0.1.0` bundle.

No version change was made this phase.

## Packaging findings (Workstream B)

| Item | Finding |
|---|---|
| **Offline bundle is STALE** | `CLE-OFFLINE-BUNDLE-0.1.0` was built **2026-09-08** (Phase 13), *before* orchestration. Its integrity is valid (152/152 checksums) but its **CLE source/config predate Phases 14–16**. A fresh offline release MUST rebuild it from `8cb2c97` (`build-offline-bundle.ps1`). **Release blocker for the offline-install path.** |
| Portable artifact is current | `dist/CLE-Install.zip` regenerated from source (`package-portable.ps1 -Zip`): 70 files, 0.12 MB, SHA256 `5EF4C923…` (full hash in the manifest). Contains the `orchestration:` config and current `cle` package. |
| No new runtime deps | orchestration/validated-coding use stdlib only; `pyproject` deps unchanged (`typer`, `rich`, `httpx`, `PyYAML`). Offline wheel set (25) still covers them. |
| Artifact hygiene | no API keys / credentials / personal paths. (The `CLE_SETUP_OK` "token" in `setup.ps1` is a smoke-test marker, not a secret.) |

## Reproducibility (Workstream B.3)

- Portable bundle: deterministic from source (`package-portable.ps1`), re-run
  gives the same file set. The **zip is not byte-for-byte reproducible** (zip
  stores timestamps); the *contents* are reproducible. Documented, not claimed
  as bit-identical.
- Offline bundle: rebuild requires models already pulled in Ollama; not
  byte-for-byte reproducible (model blob metadata + installer bytes). Build
  inputs are recorded in its `manifest.json`.

## Files changed this phase

Docs only (PHASE-17-*, RELEASE-NOTES-0.1.0, RELEASE-CANDIDATE-MANIFEST) +
CHANGELOG. The portable zip was regenerated (git-ignored build artifact). **No
source/runtime changes; no tag; no publish; no version bump.**

## Outstanding release blockers

1. **Offline bundle stale** — rebuild from `8cb2c97` before any offline-install
   release (or ship only the online/portable path and mark offline as a known gap).
2. **Genuine network-isolated acceptance BLOCKED** — no disconnected machine.
3. Decide the version label (0.1.0-rebuilt vs 0.2.0) — authorizer's call.
