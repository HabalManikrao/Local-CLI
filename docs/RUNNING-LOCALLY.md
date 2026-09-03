# Running Local CLE on Your Machine

A step-by-step guide to installing and running Local CLE **offline** on a local
system. Primary target is **Windows** (PowerShell), with notes for macOS/Linux.

Everything runs on your machine: the models run in Ollama on `localhost`, and
the index/memory/logs are local files. No internet is needed after the one-time
install of dependencies and models.

---

## 1. Prerequisites

| Tool | Why | Check |
|------|-----|-------|
| **Python 3.11+** | runtime | `python --version` |
| **Ollama** | local LLM provider | `ollama --version` |
| **Git** | checkpoints / rollback | `git --version` |
| **ripgrep** (`rg`) | fast search (optional; Python fallback exists) | `rg --version` |

Install any that are missing:

- Python — <https://www.python.org/downloads/> (tick "Add to PATH" on Windows).
- Ollama — <https://ollama.com/download>
- Git — <https://git-scm.com/downloads>
- ripgrep — <https://github.com/BurntSushi/ripgrep> (or `winget install BurntSushi.ripgrep.MSVC`)

> **Recommended hardware:** Intel i5 / 32 GB RAM / NVIDIA RTX 3060 Ti (8 GB VRAM)
> or similar. An 8 GB GPU comfortably runs ~3B–8B models; pick model sizes per
> role accordingly (see step 4).

---

## 2. Start Ollama and pull models

Start the Ollama daemon (leave it running in its own terminal, or use the
desktop app which runs it in the background):

```powershell
ollama serve
```

In another terminal, pull models. Good starting points for an 8 GB GPU:

```powershell
ollama pull llama3.2            # small & fast — good for 'fast'
ollama pull qwen2.5-coder:7b    # coding — good for 'coding'
ollama pull qwen2.5:7b          # reasoning/debugging — good for 'reasoning'
ollama pull nomic-embed-text    # embeddings — for semantic search
```

Any models work — CLE never hard-codes model names. Verify:

```powershell
ollama list
```

---

## 3. Install Local CLE

From the project directory (`C:\Projects\Local CLI`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

This installs the `cle` command into the virtual environment. Optional extras:

```powershell
pip install -e ".[semantic]"   # FAISS (faster semantic search; optional)
pip install -e ".[parsing]"    # tree-sitter (more precise Java parsing; optional)
pip install -e ".[dev]"        # pytest etc. (for development)
```

> **Activating the venv later.** Each new terminal:
> ```powershell
> cd "C:\Projects\Local CLI"; .\.venv\Scripts\Activate.ps1
> ```
> If PowerShell blocks activation, allow local scripts once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
> You can always call it without activating: `.\.venv\Scripts\cle.exe <args>`.

**macOS/Linux equivalent:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## 4. Point CLE at a project and configure models

`cd` into the codebase you want to work on (it can be any repo — e.g. a Java /
Winium automation project), then:

```powershell
cle doctor            # validate the environment
cle init              # create .cle/ (project config) in this directory
```

`cle doctor` checks Python, Git, ripgrep, SQLite, the Ollama client, the Ollama
**daemon** connection, GPU, configured models, and project config — and prints a
concrete fix for anything that is not ready.

Assign your pulled models to the four **roles**:

```powershell
cle model use fast      llama3.2
cle model use coding    qwen2.5-coder:7b
cle model use reasoning qwen2.5:7b
cle model use embedding nomic-embed-text
cle models            # confirm roles + installed models
```

Roles are stored in `.cle/config.yaml` and can be changed anytime without code
changes. (Details: [MODEL-ROUTING.md](MODEL-ROUTING.md).)

If the target project is not yet a git repo, initialize it so checkpoints work:

```powershell
git init
```

---

## 5. Index the codebase

```powershell
cle index             # build the code index (files / symbols / imports)
cle embed             # optional: build the semantic index (needs embedding model)
cle status            # or: cle dashboard   — see project/model/index state
```

`cle index` writes `.cle/index/index.db`. Re-run it after significant code
changes.

---

## 6. Everyday usage

```powershell
# Understand the code
cle ask "Explain what this project does"
cle search "driver initialization"
cle search -i -F "Thread.sleep("        # case-insensitive, literal
cle symbol WiniumDriver                 # structural lookup by name
cle explain src/main/java/DriverManager.java

# Java / Winium intelligence (read-only; no changes)
cle java analyze
cle winium analyze

# Make changes safely (plan -> preview diff -> you approve -> apply)
cle code "Refactor the driver initialization into a factory"
cle diff                                # review the working-tree changes
cle rollback                            # undo to the last checkpoint

# Tests & debugging
cle test                                # detect build system, run tests
cle debug                               # diagnose failures (no changes)
cle fix-tests                           # bounded loop: run -> fix -> re-run

# Autonomous (bounded, still asks before edits by default)
cle autopilot "Optimize the login automation module"

# Project memory
cle memory add decision "Use explicit waits" "Winium sleeps are flaky"
cle memory set test_command "mvn -q test"
cle memory show

# Benchmark your models/agents on local tasks
cle benchmark
```

Add `--help` to any command (e.g. `cle code --help`) for its options.

### Safety at a glance
- Reads, search, `git status`, and running tests are allowed automatically.
- **Writes, deletes, and commits require your approval.** Deletion is disabled
  unless you enable `safety.allow_delete`. Network is off by design.
- `cle code` / `cle autopilot` take a **git checkpoint before editing**, so
  `cle rollback` always gets you back. (Details: [SAFETY.md](SAFETY.md).)

---

## 7. Where things live

```
<your project>/.cle/
  config.yaml                  # project config + model roles
  index/index.db               # code index (files/symbols/imports/embeddings)
  memory/memory.db             # project memory + sessions
  checkpoints/checkpoints.json # rollback snapshots
  benchmarks/benchmark-*.json  # benchmark results
<your project>/logs/<date>/session-*.json   # audit trail of every run
```

All local; safe to delete `.cle/` and `logs/` to reset (you'll just need to
`cle init` / `cle index` again).

---

## 8. Troubleshooting

| Symptom | Fix |
|--------|-----|
| `Could not connect to Ollama at http://127.0.0.1:11434` | Start it: `ollama serve` (or open the Ollama app). Re-run `cle doctor`. |
| `No model configured for role 'coding'` | `cle model use coding <model>` (after `ollama pull <model>`). |
| `Ollama model 'X' is unavailable` | `ollama list` to see names; `ollama pull X`; names include the tag (e.g. `qwen2.5:7b`). |
| `The project is not indexed yet` | `cle index`. |
| Semantic search returns nothing | Run `cle embed` (needs an `embedding` model). |
| `not a git repository` on checkpoint/rollback | `git init` in the project. |
| `rg not found` (WARN) | Optional — install ripgrep, or ignore (a Python fallback is used). |
| GPU shows "unknown" in `cle doctor` | Install the NVIDIA driver so `nvidia-smi` is available; CLE still works on CPU. |
| Model too slow / out of VRAM | Use a smaller model for that role (e.g. a 3B for `coding`), or a quantized tag. |
| PowerShell won't activate the venv | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or call `.\.venv\Scripts\cle.exe` directly. |

---

## 9. A quick end-to-end smoke test

```powershell
cd "C:\Projects\Local CLI"
.\.venv\Scripts\Activate.ps1
cle doctor            # should pass once Ollama is running and models assigned
cle init
cle index
cle ask "Summarize this project's architecture"
```

If `cle ask` returns a sensible answer, your local setup is working end-to-end.

See also: [ARCHITECTURE.md](ARCHITECTURE.md) · [MODEL-ROUTING.md](MODEL-ROUTING.md)
· [SAFETY.md](SAFETY.md) · [TESTING.md](TESTING.md) · [JAVA-WINIUM.md](JAVA-WINIUM.md)
