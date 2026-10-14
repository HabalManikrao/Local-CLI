# Using Local CLE

A task-oriented guide to driving the `cle` command. Everything runs locally
against an Ollama daemon on `localhost` — no cloud, no data leaving your machine.

If you haven't installed yet, start with
[`RUNNING-LOCALLY.md`](RUNNING-LOCALLY.md) (setup) or run `.\setup.ps1`. For the
command catalog at a glance, see the table in [`../README.md`](../README.md).

---

## 1. The mental model (read this first)

Three ideas explain almost everything:

- **Roles, not model names.** CLE never hard-codes a model. It maps a *task
  intent* to a *role* (`fast`, `coding`, `reasoning`, `embedding`) and you assign
  whatever Ollama model you like to each role. Swap models any time with
  `cle model use` — no code or config edits.
- **Nothing changes without approval.** Commands that edit files (`code`,
  `fix-tests`, `autopilot`) always show a plan + diff and ask before writing.
  Every risky run is snapshot-protected so you can `cle rollback`.
- **It works offline, and tells you the truth.** Answers are grounded in your
  local code. `cle doctor` reports exactly what's available (daemon up? models
  pulled? GPU?) so there's no guessing.

> **CPU note.** On a machine without a GPU, the bigger models are slow — a
> context-heavy `explain`/`code` can take a few minutes. That's expected; the
> default timeout is 300s. Use a small model for the `fast` role to keep
> quick commands snappy.

---

## 2. Quick start (first five minutes)

```powershell
# 0) one-time: make sure the environment is healthy
cle doctor

# 1) in your project directory, initialize CLE (creates .cle/)
cd C:\path\to\your\project
cle init

# 2) point roles at models you've pulled in Ollama (ollama pull <model> first)
cle model use fast       llama3.2          # quick answers
cle model use coding     llama3.1:8b       # code changes
cle model use reasoning  llama3.1:8b       # explain / debug / architecture
cle model use embedding  nomic-embed-text  # semantic search
cle models                                 # confirm the assignments

# 3) build the local code index
cle index

# 4) ask it something about your code
cle ask "What does this project do?"
cle explain src/main.py
```

`cle status` or `cle dashboard` gives you the current picture any time.

---

## 3. Understand a codebase

| Goal | Command |
|---|---|
| Build/refresh the code index | `cle index` |
| Exact text search (fast) | `cle search "TODO"`  ·  `-i` case-insensitive  ·  `-F` literal |
| Find a symbol by name | `cle symbol UserService` |
| Explain one file (uses the reasoning model) | `cle explain src/app/user.py` |
| One-shot question (uses the fast model) | `cle ask "Where is auth handled?"` |
| Interactive conversation | `cle chat` (type `exit` or Ctrl-C to quit) |
| Semantic ("find similar code") search | `cle embed` first, then it powers retrieval |

Notes:
- **`ask` vs `explain`.** `ask` is a quick, *context-free* one-shot — great for
  general questions, but it does **not** read your repo, so don't ask it
  project-specific questions. `explain` and `code` *do* pull in your real code.
- **`embed` is a one-time (per-change) build** and can take several minutes on a
  real repo; it shows a progress bar. Re-run it after large code changes. If you
  switch the embedding model, re-run `cle embed` — CLE will otherwise tell you
  the index is stale rather than return garbage.

---

## 4. Make a change safely

The core loop is **plan → review → approve → apply → verify → (undo if needed)**.

```powershell
# propose a change — shows a plan and a diff, then asks before writing
cle code "Add input validation to the login handler"

# preview only, never writes
cle code "Rename the Foo class to Bar" --no-apply

# skip the prompt (you trust it / running unattended)
cle code "Add a docstring to utils.py" --yes
```

Safety net around edits:

```powershell
cle checkpoint "before refactor"   # snapshot (non-destructive)
cle diff                           # see working-tree changes + status
cle rollback                       # restore tracked files to the latest checkpoint
cle rollback 3                     # ...or to a specific checkpoint id
```

`rollback` only restores **tracked** files and never deletes new files you added
since the checkpoint — it reports them and leaves them in place. A git repo is
required for checkpoints; run `git init` if `cle init` warned you.

---

## 5. Run, diagnose, and fix tests

```powershell
cle test        # detect the build system (pytest/maven/gradle) and run tests
cle debug       # run tests and, if they fail, explain the root cause (no edits)
cle fix-tests   # bounded loop: run → diagnose → propose fix → re-run (asks before applying)
```

`fix-tests` is iteration-capped (default from config, `agent.max_iterations`).
It asks before applying each fix unless you pass `-y`.

---

## 6. Autopilot (hands-off, bounded)

For a whole task end-to-end — plan, edit, build, test, and self-repair:

```powershell
cle autopilot "Add a /health endpoint returning {status: ok} and a test for it"
cle autopilot "..." --yes            # auto-approve edits
cle autopilot "..." --max-iter 3     # cap the repair loop
```

Autopilot is still bounded and git-protected: it checkpoints first, stops at the
iteration cap, and you can `cle rollback` the whole thing. Start with `--max-iter`
small and review the diff. Output quality depends on the model behind the
`coding`/`reasoning` roles — a stronger local model gives better edits.

---

## 7. Project memory

CLE remembers project-specific facts so you don't repeat them:

```powershell
cle memory show                                  # list entries + settings
cle memory add decision "Use SQLite for the cache" "Simplicity over a server"
cle memory set test_command "pytest -q"          # scalar settings (build/test cmds...)
cle memory remove 4                              # delete entry #4
cle memory clear                                 # wipe project memory
```

Setting `test_command` lets `test`/`debug`/`fix-tests` use your exact command
instead of guessing.

---

## 8. Specialized analysis (read-only, evidence-backed)

```powershell
cle java analyze       # static Java quality findings — no changes
cle winium analyze     # Winium automation-code smells — no changes
```

These never modify code; every finding cites the file/line it came from.

---

## 9. Models, benchmarking, and status

```powershell
cle models                       # roles + installed Ollama models
cle model use reasoning qwen3:1.7b   # reassign a role (e.g. a faster model on CPU)
cle benchmark                    # time the configured models/agents on local tasks
cle status  /  cle dashboard     # project, provider, roles, index, git at a glance
```

**Choosing models (rough guide):**

| Role | What it does | Good fit |
|---|---|---|
| `fast` | `ask`, `chat`, quick routing | a small, snappy model (1–3B) |
| `coding` | `code`, `fix-tests`, `autopilot` edits | the strongest code model you can run |
| `reasoning` | `explain`, `debug`, architecture | a capable general model (7–8B+) |
| `embedding` | semantic search | a dedicated embedding model (e.g. `nomic-embed-text`) |

On CPU-only machines, prefer smaller models for `reasoning` to avoid long waits.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Anything model-related fails | `cle doctor` — it pinpoints daemon/model/GPU issues with a remedy |
| "Ollama request timed out" | The model is slow on CPU. Use a smaller model for that role, or raise `provider.timeout_seconds` in `.cle/config.yaml` |
| "not indexed yet" | Run `cle index` (and `cle embed` for semantic search) |
| Wrong/empty answers from `ask` | `ask` has no project context by design — use `explain`/`code`/`chat` for code-aware answers |
| Semantic search says the index is stale | You changed the embedding model — re-run `cle embed` |
| A command errored oddly | Re-run with `-v`/`--verbose` for the full trace |

Configuration lives in `.cle/config.yaml` (per-project, deep-merged over
[`../configs/default.yaml`](../configs/default.yaml)). Common keys:
`provider.timeout_seconds`, `provider.num_ctx`, `context.max_tokens`,
`agent.max_iterations`, and the `models.*` role assignments.

---

## Command reference (one-liners)

```
cle init          initialize a CLE project (.cle/)
cle doctor        validate environment (python/git/ripgrep/ollama/models/gpu)
cle status        project / provider / roles / index status
cle dashboard     the same, as a panel view
cle models        list roles + installed models
cle model use R M assign model M to role R
cle index         build the code index (files/symbols/imports)
cle search PAT    exact search (-i case-insensitive, -F literal)
cle symbol NAME   find a symbol structurally
cle explain FILE  explain a file (context-aware)
cle embed         build the semantic index
cle ask "Q"       one-shot, context-free question
cle chat          interactive chat
cle code "REQ"    plan→approve→apply a change (-y apply, --no-apply preview)
cle test          run the project's tests
cle debug         diagnose failing tests (no edits)
cle fix-tests     bounded run→diagnose→fix loop (-y to auto-apply)
cle autopilot "T" autonomous plan→edit→test→repair (--max-iter N, -y)
cle diff          working-tree diff + status
cle checkpoint L  snapshot you can roll back to
cle rollback [ID] restore tracked files to a checkpoint (-y to skip confirm)
cle memory ...    show / add / set / remove / clear project memory
cle java analyze     read-only Java findings
cle winium analyze   read-only Winium findings
cle benchmark     benchmark models/agents on local tasks
```

Every command supports `--help`. Add `-v` to any command for verbose logging.
