# CLE 0.1.0 — Release Notes (candidate)

**Local CLI Engineering (CLE)** — an offline-first, Ollama-powered local software
engineering agent. Understand your codebase, ask a local model, make controlled
changes, and validate them with your tests — all on your machine.

> Candidate prepared from commit `8cb2c97`. Not yet tagged or published.

## Verified capabilities

- **Local, offline-first** engineering assistant over Ollama (`localhost`); core
  runs without internet after install.
- **Code understanding:** `cle index`, `cle search`, `cle symbol`, `cle explain`
  — fast structural navigation (symbol lookup measured 100% on the internal
  benchmark).
- **Ask / chat:** `cle ask` (streams; supports UNIX pipes, e.g. `type log | cle ask "…"`), `cle chat`.
- **Model routing by role** (`fast`/`coding`/`reasoning`/`embedding`) with no
  hard-coded model names; override per command with `--model`.
- **Multi-model orchestration (opt-in):** `--ensemble` (several models answer, a
  synthesiser reconciles + flags disagreement), `cle debug --multi-model`;
  honest `complete/partial/fallback` status + routing/telemetry observability.
- **Controlled code changes:** `cle code` (plan → preview diff → approve →
  guarded apply → checkpoint). `--review` adds an advisory second-model review
  (reports independence). **`--validate`** runs your tests against the applied
  change and reports `VALIDATED` / `VALIDATION_FAILED` / `VALIDATION_SKIPPED`
  (failing tests are never reported as success).
- **Debug / fix-tests / autopilot:** bounded, approval-gated, git-checkpointed.
- **Safety:** all writes/shell/git go through a permission guard; `cle checkpoint`
  / `cle rollback`; audit log under `logs/`.
- **Offline tooling:** `install.cmd` (double-click), `setup.ps1`, portable bundle
  (`package-portable.ps1`), offline bundle + `verify.ps1` (checksum integrity).

## Known limitations (please read)

- **Answer quality depends on your local model**, and **CPU inference is slow**
  (minutes for 8B models). Small models give weak results.
- **Multi-model is opt-in and costly:** ensembles ran **7–17× slower** than
  single-model with **no proven quality gain** on a small sample. Default stays
  single-model; use `--ensemble`/`--review` deliberately.
- **Genuine network-isolated offline install has NOT been accepted** (no
  disconnected test machine); verified only via checksums + dependency
  inspection. The shipped **offline bundle is stale** and must be **rebuilt** for
  an offline release.
- **Autopilot multi-model orchestration is deferred** (readiness checklist in
  `docs/PHASE-15-AUTOPILOT-READINESS.md`).
- **Semantic-retrieval recall@k not measured;** structural retrieval is (recall 1.0).
- **No provider-level cancellation** (a timed-out Ollama call keeps running until
  the provider timeout); no VRAM-aware scheduling (conservative concurrency cap).
- Not a claim of universal production-readiness.

## Install (summary)

- **Easiest:** download the portable folder/zip, double-click `install.cmd`.
- **Full:** `.\setup.ps1`. See `README.md`, `docs/USAGE.md`,
  `docs/RUNNING-LOCALLY.md`, `docs/TROUBLESHOOTING.md`.
- **Offline:** rebuild the bundle (`build-offline-bundle.ps1`), copy it, then
  `setup.ps1 -Offline` on a machine that already has Python/Git/Ollama.

## Safe usage of code-modification commands

- Preview first: `cle code "…" --no-apply`. Apply only on approval.
- Validate: `cle code "…" --validate` runs your tests; undo with `cle rollback`.
- `--review` is advisory (a model opinion), **not** objective validation — your
  tests are the ground truth.

## First-run verification

```
cle doctor            # environment health
cle ask "hello"       # confirm a local model responds
```
