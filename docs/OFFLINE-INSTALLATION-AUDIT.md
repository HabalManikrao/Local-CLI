# OFFLINE INSTALLATION AUDIT — Local CLE (Phase 13)

**Date:** 2026-09-04
**Scope:** make CLE installable on a **fully offline** Windows machine via a
prebuilt bundle. No core CLE architecture changes.

---

## 0. Executive summary

CLE already runs offline *after* install (Ollama on localhost, local index/
memory), and the Phase-12 `setup.ps1` automates online install via winget + pip
+ `ollama pull`. What's missing is a way to **prepare** everything on an
internet PC and install it on a machine with **no internet at all**.

The plan: a `build-offline-bundle.ps1` (online) that collects the OS installers,
Python wheels (`pip download`), the required Ollama models (copied from the
content-addressed on-disk store), CLE source + config, a `manifest.json`, and
`SHA256SUMS.txt`; and a strict `setup.ps1 -Offline` (offline) that verifies
checksums, installs from the bundle only (`pip --no-index --find-links`,
bundled installers, model-store import), then runs `cle doctor`, the test suite,
and a **real** Ollama smoke test — **never touching the network**.

Everything reuses the existing seams: `pyproject.toml` (deps), `cle model use`
(roles), `cle doctor`/`init`/`ask`, and the `CleSetup.psm1` helpers.

---

## 1. Current setup process

`setup.ps1` (Phase 12): preflight → detect/winget-install prereqs → venv → pip
`-e .[dev]` → start+health-check Ollama → `ollama pull` models → `cle init` +
`cle model use` → `cle doctor` → pytest → real `cle ask` smoke → report. Modes:
`-NonInteractive -SkipModels -Repair -Verify -Help`. Helpers live in
`scripts/CleSetup.psm1`.

## 2. Required prerequisites
Python 3.11+, Git, Ollama (daemon on `http://127.0.0.1:11434`). SQLite is stdlib.

## 3. Optional prerequisites
ripgrep (Python fallback exists), FAISS/tree-sitter/Textual (graceful), NVIDIA GPU.

## 4. Python requirements
`pyproject.toml` → `requires-python = ">=3.11"`. Deps: `typer, rich, httpx,
PyYAML`; dev: `pytest, pytest-cov`. Console script `cle`.

## 5. Git requirements
Any recent Git (checkpoints/rollback). No config changes.

## 6. Ollama requirements
Client + reachable local API. Version here: **0.24.0**.

## 7. Python package dependencies
Authoritative in `pyproject.toml`. Offline install must use
`pip install --no-index --find-links <packages> -e .[dev]` with **all
transitive wheels** pre-downloaded (incl. a matching `pip`/`setuptools`/`wheel`).

## 8. Model requirements
Roles `fast/coding/reasoning/embedding` → models via `cle model use` (never
hard-coded). Sizes are multi-GB.

## 9. Existing installer behavior
Idempotent, detect-before-install, refreshes PATH, actionable stop-with-remedy,
per-run log in `logs/`, ASCII-only for PS 5.1.

## 10. Existing configuration
Packaged `configs/default.yaml`; project `.cle/config.yaml` (deep-merged).
`provider.host` parsed by the installer for health checks.

## 11. What already works offline
Core CLE runtime (indexing, retrieval, memory, agents, search, git, analysis,
autopilot), Ollama on localhost, the whole test suite (faked provider).

## 12. What currently requires internet
winget installs, `pip install` (PyPI), `ollama pull` (registry). Phase 13
removes all three from the offline path.

## 13. Proposed offline bundle structure

The Ollama store is **content-addressed** — verified on this machine:

```
%USERPROFILE%\.ollama\models\
  manifests\registry.ollama.ai\library\<name>\<tag>   # JSON: config.digest + layers[].digest
  blobs\sha256-<digest>                               # layer data, keyed by digest
```

Ollama 0.24 has **no** `export`/`import` command, so the safe, supported
transfer is to copy the specific manifest(s) + the blobs they reference and
**merge** them into the target store. Because blobs are digest-keyed, import is
idempotent and cannot corrupt existing models (identical digest = identical
bytes; existing blobs are skipped). Blobs are **shared/deduplicated** across
models in the bundle to save space.

```
CLE-OFFLINE-BUNDLE-<ver>/
  setup.ps1  verify.ps1  setup.cmd
  scripts/CleSetup.psm1
  manifest.json
  README-OFFLINE.txt
  checksums/SHA256SUMS.txt
  installers/{python,git,ollama}/*.exe
  packages/*.whl            # pip download of .[dev] + pip/setuptools/wheel
  models/
    manifests/registry.ollama.ai/library/<name>/<tag>
    blobs/sha256-<digest>   # deduplicated
    models-index.json       # role -> {model, tag, digests[], sizeBytes}
  cle/  configs/  pyproject.toml  README.md  tests/   # CLE source
  docs/
  logs/
```

The offline installer imports models by merge-copying `models/manifests` and
`models/blobs` into the machine's `OLLAMA_MODELS` dir.

## 14. Risks

| Risk | Mitigation |
|------|------------|
| Missing transitive wheel → offline pip fails | `pip download` the full `.[dev]` set incl. build backend; verify a fresh venv installs `--no-index` in the builder |
| Wheels are platform/Python-version specific | Download on Win + a Python matching the bundled installer's minor version; record versions in manifest; offline installer checks compatibility |
| Ollama on-disk format changes across versions | Record source Ollama version + model digests in manifest; installer warns if target Ollama major differs; digests verified on import |
| Corrupting an existing Ollama store | Only add missing blobs/manifests (digest-keyed); never delete; back off if a digest mismatch is detected |
| Huge bundle silently fills disk | Builder prints per-item + total size before writing; offline installer checks free space with margin before installing |
| Tampered/partial USB copy | SHA256 every artifact; `verify.ps1` + preflight refuse install on mismatch |
| Accidental network calls in offline mode | `pip --no-index`; no winget/`ollama pull`; explicit "Network: DISABLED" banner; strict stop on any missing artifact |

## 15. Recovery strategy

- `verify.ps1` — bundle integrity only, no changes, non-zero on failure.
- `setup.ps1 -Offline -Verify` — read-only machine + bundle readiness.
- `setup.ps1 -Offline -Repair` — recreate venv, reinstall wheels, start daemon,
  re-import missing models, re-validate; never wipes working config.
- Missing required model / checksum mismatch → **STOP** with the exact artifact
  and "rebuild the bundle with build-offline-bundle.ps1" (no download attempt).
- Per-run logs in `logs/`.

## 16. Reuse decisions

| Concern | Reuse |
|---------|-------|
| Deps list | `pyproject.toml` (via `pip download` / `--no-index`) |
| Roles | `cle model use` |
| Validation / init / smoke | `cle doctor` / `cle init` / `cle ask` |
| Detection/log/version/model-match | `scripts/CleSetup.psm1` (extended, not rewritten) |
| Online setup flow | `setup.ps1` phases (extended with `-Offline` branches) |

No core CLE code changes are required by this phase (only installer/packaging).

## 17. Known limitations (by design)

- The offline machine can only install software/models **included in the
  bundle**. New models require rebuilding the bundle on an online PC and
  re-transferring (`-Repair` picks up additions).
- Wheels match the bundled Python's minor version and Windows/amd64.
- No auto-update — updates are deliberate via a new versioned bundle.
