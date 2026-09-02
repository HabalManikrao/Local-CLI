# Architecture

Local CLE is an offline-first, Ollama-powered local engineering agent. It is a
single Python package (`cle/`) with strictly downward-pointing layers and a few
non-negotiable choke points.

```
                         LOCAL CLE
                            │
                    ┌───────▼────────┐
                    │  CLI (Typer)   │   cle/cli
                    └───────┬────────┘
                            │
          ┌─────────────────┼──────────────────┐
          │                 │                  │
      Agents            Analysis            Benchmark
   cle/agents         cle/analysis         cle/benchmark
   coding/testing/    java/winium          harness/tasks
   debugging
          │                 │
          └───────┬─────────┘
                  │
        ┌─────────▼─────────┐     ┌──────────────┐
        │  Context engine   │────▶│   Indexing   │
        │  cle/context      │     │  cle/indexing│  SQLite
        │  retrieval/embed  │     │  symbols/db  │
        └─────────┬─────────┘     └──────────────┘
                  │
        ┌─────────▼─────────┐
        │   Model layer     │  cle/models
        │  provider/router/ │  (single LLM choke point)
        │  registry         │
        └─────────┬─────────┘
                  │
               Ollama (localhost)

        Cross-cutting: cle/tools (search/git/filesystem/edits/test_runner),
        cle/safety (permissions/audit), cle/memory (SQLite), cle/evidence.
```

## Choke points (enforced seams)

- **`models.base.ModelProvider`** — the only place that talks to an LLM.
  `OllamaProvider` today; future online providers implement the same interface
  without touching callers.
- **`models.router.ModelRouter` + `registry.ModelRegistry`** — intent → role →
  model. No model names are hard-coded; roles are configured.
- **`safety.permissions.PermissionGuard` + `tools.filesystem.FileSystem`** — the
  only path to writes/shell/git mutation. LLMs never act directly.
- **`evidence.EvidenceSource`** — `LOCAL | CACHED | LIVE`, never upgraded to LIVE.

## Layers

| Layer      | Package        | Responsibility                                   |
|------------|----------------|--------------------------------------------------|
| CLI        | `cle/cli`      | Typer app, command impls, Rich UI                |
| Agents     | `cle/agents`   | coding, testing, debugging (plan→approve→act)    |
| Analysis   | `cle/analysis` | Java + Winium static findings                    |
| Context    | `cle/context`  | chunking, embeddings, retrieval, assembly        |
| Indexing   | `cle/indexing` | file/symbol/import index (SQLite)                |
| Models     | `cle/models`   | provider, router, registry                       |
| Tools      | `cle/tools`    | search, git, filesystem, edits, test_runner      |
| Safety     | `cle/safety`   | permissions, audit                               |
| Memory     | `cle/memory`   | project-scoped SQLite knowledge                  |
| Benchmark  | `cle/benchmark`| task harness + built-in tasks                    |

## Data locations (per project)

```
<project>/.cle/
  config.yaml                 # project config overrides
  index/index.db              # code index (files/symbols/imports/embeddings)
  memory/memory.db            # project memory + sessions
  checkpoints/checkpoints.json# rollback snapshots
  benchmarks/benchmark-*.json # benchmark results
<project>/logs/<date>/session-*.json   # audit trail
```

## Offline & Windows

Core runs without internet after install; Ollama is on `localhost`. Everything
uses `pathlib` + UTF-8; git and processes are driven via `subprocess`. GPU and
optional native deps (FAISS, tree-sitter) degrade gracefully — see
[ARCHITECTURE-AUDIT.md](ARCHITECTURE-AUDIT.md).

See also: [MODEL-ROUTING](MODEL-ROUTING.md), [CONTEXT-ENGINE](CONTEXT-ENGINE.md),
[AGENT-ARCHITECTURE](AGENT-ARCHITECTURE.md), [SAFETY](SAFETY.md),
[MEMORY](MEMORY.md), [TESTING](TESTING.md), [JAVA-WINIUM](JAVA-WINIUM.md).
