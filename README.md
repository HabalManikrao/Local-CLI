# Local CLE — Local CLI Engineering

An **offline-first, Ollama-powered local software engineering agent**. CLE
understands your codebase before acting, uses the appropriate local model for
each task, makes controlled changes, verifies them through tests, and keeps an
auditable trail — all on your machine, no cloud required.

> Status: **Milestone 1 (CLI Foundation)**. Later milestones add repository
> indexing, semantic/structural retrieval, project memory, and engineering
> agents. See [`docs/ARCHITECTURE-AUDIT.md`](docs/ARCHITECTURE-AUDIT.md).

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com/download) (running locally)
- Git, and (recommended) [ripgrep](https://github.com/BurntSushi/ripgrep)

## Install (development)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Quick start

```powershell
cle doctor                       # validate your environment
cle init                         # initialize a CLE project (creates .cle/)
ollama pull llama3.2             # pull any model you like
cle model use fast llama3.2      # assign it to the 'fast' role
cle model use coding llama3.2    # ...and other roles
cle models                       # list roles + installed models
cle ask "Explain this project"   # one-shot question
cle chat                         # interactive chat
```

## Commands (Milestone 1)

| Command | Purpose |
|---|---|
| `cle init` | Initialize a CLE project in the current directory |
| `cle doctor` | Validate Python, Git, ripgrep, SQLite, Ollama, GPU, models, project |
| `cle status` | Show project, provider, model roles, index status |
| `cle models` | List configured roles and installed Ollama models |
| `cle model use <role> <model>` | Assign a model to a role (fast/coding/reasoning/embedding) |
| `cle ask "<question>"` | One-shot question (routed to the `fast` model) |
| `cle chat` | Interactive chat session |

## Configuration

Defaults live in [`configs/default.yaml`](configs/default.yaml). Project
overrides go in `.cle/config.yaml` (created by `cle init`) and are deep-merged
over the defaults. No model names are hard-coded — roles are assigned via
`cle model use`.

## Development

```powershell
pytest                # run the full suite (offline; no daemon needed)
pytest tests/unit     # unit tests only
```

Architecture and design docs live under [`docs/`](docs/).
