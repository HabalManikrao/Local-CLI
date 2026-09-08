# Completely Offline Installation

Install Local CLE on a Windows machine with **no internet** — no PyPI, no
GitHub, no Ollama registry. You prepare a bundle on an online PC, copy it via
USB, and install from it.

```
 Online PC                         Offline PC
 ---------                         ----------
 build-offline-bundle.ps1  --USB-->  setup.ps1 -Offline
```

## 1. Build the bundle (online PC)

On a Windows machine **with** internet, Python 3.11+, and the models you want
already pulled in Ollama:

```powershell
# pull the models you want to ship first, e.g.:
ollama pull llama3.2
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# then build:
.\build-offline-bundle.ps1
```

This collects into `dist\CLE-OFFLINE-BUNDLE-<version>\`:

- **installers/** — Python, Git, Ollama Windows installers
- **packages/** — every Python wheel (`pip download` of the project + build backend)
- **models/** — the required Ollama models: each model's manifest plus the
  blobs it references, copied from your local store (`%USERPROFILE%\.ollama\models`)
  and **de-duplicated** (shared layers stored once)
- **cle/, configs/, tests/, pyproject.toml, setup.ps1, verify.ps1, scripts/** — CLE itself
- **manifest.json** + **checksums/SHA256SUMS.txt**

It prints a size summary (installers / packages / models / total) before you copy.

### Choosing models

By default the builder packages the roles from `.cle\config.yaml` (or the
built-in recommended defaults), for whichever models are present in your local
store. Override explicitly:

```powershell
.\build-offline-bundle.ps1 -Models fast=llama3.2,coding=qwen2.5-coder:7b,reasoning=qwen2.5:7b,embedding=nomic-embed-text
```

Useful flags: `-SkipInstallers`, `-SkipModels`, `-Force` (re-download),
`-OutputRoot <dir>`, `-PythonInstallerUrl/-GitInstallerUrl/-OllamaInstallerUrl`.

## 2. Transfer

Copy the whole `CLE-OFFLINE-BUNDLE-<version>` folder to the offline machine
(USB / external drive). Nothing else is needed.

## 3. Verify (offline PC, optional but recommended)

```powershell
cd CLE-OFFLINE-BUNDLE-<version>
.\verify.ps1
```

Checks the manifest and **every** SHA256 checksum, plus the presence of
installers, wheels, and model artifacts. Non-zero exit if anything is wrong —
makes no changes.

## 4. Install (offline PC)

```powershell
.\setup.ps1 -Offline
```

(or `setup.cmd -Offline` if PowerShell blocks scripts.)

Offline install is **strict**: it prints

```
OFFLINE MODE
Network downloads: DISABLED
Package index:     DISABLED
Remote model pulls: DISABLED
```

and never contacts the network. `pip` runs with `--no-index --find-links
packages` (and `PIP_NO_INDEX=1`); prerequisites come from `installers\`; models
are imported by copying into the Ollama store — never `ollama pull`.

Phases: preflight (checksums + disk + prereqs) → install Python/Git/Ollama from
the bundle (or reuse compatible existing ones) → create `.venv` → install wheels
`--no-index` → start & health-check Ollama → import models → configure roles →
`cle doctor` → test suite → **real** `cle ask` smoke test → report.

### Modes

```powershell
.\setup.ps1 -Offline -Verify         # read-only readiness check (CI-friendly)
.\setup.ps1 -Offline -Repair         # fix only what's broken (venv/deps/daemon/models)
.\setup.ps1 -Offline -NonInteractive # no prompts (automated deployment)
.\setup.ps1 -Offline -SkipModels     # install without configuring models
```

## How models transfer (and why it's safe)

Ollama's store is **content-addressed**: `manifests/.../<name>/<tag>` (JSON) plus
`blobs/sha256-<digest>`. The builder copies the manifest + referenced blobs; the
offline installer merges them into the target store. Because blobs are keyed by
their SHA256 digest, importing is idempotent and cannot corrupt existing
models — an identical digest is identical bytes, and already-present blobs are
skipped. Existing compatible models on the offline machine are **reused**, not
duplicated.

Ollama 0.24 has no `export`/`import` command; copying the content-addressed
store is the supported, reliable transfer. The source Ollama version and each
model's digests are recorded in `manifest.json` and verified on import.

## Updating an offline install

Offline installs never auto-update (reproducibility). To add a model or update
CLE:

```
Online PC:  build-offline-bundle.ps1   (new/updated artifacts)
   -> USB ->
Offline PC: .\setup.ps1 -Offline -Repair
```

`-Repair` imports newly added models and reinstalls anything missing without
disturbing working configuration.

## Limitations

- The offline machine can only install software/models **in the bundle**.
- Wheels match the bundled Python's minor version (Windows/amd64). Build the
  bundle with a Python matching the target (the builder pins the Python
  installer to its own version).
- No GPU driver installation — CPU inference works; GPU is used automatically if
  a compatible NVIDIA driver is already present.

See [OFFLINE-INSTALLATION-AUDIT.md](OFFLINE-INSTALLATION-AUDIT.md) for the design
and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for fixes.
