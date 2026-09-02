# Model Routing

CLE never hard-codes model names. It routes work through two configurable
layers so you can swap models without touching code.

## Roles

Four task roles, each mapped to an Ollama model in config:

| Role        | Used for                                   |
|-------------|--------------------------------------------|
| `fast`      | quick, low-latency answers                 |
| `coding`    | code generation / modification             |
| `reasoning` | debugging, architecture, hard reasoning    |
| `embedding` | embeddings for semantic search             |

Assign a model to a role:

```bash
ollama pull llama3.2
cle model use fast llama3.2
```

Stored in `.cle/config.yaml` under `models:`.

## Intents → Roles → Models

A task has an *intent*. The router maps intent → role (via `routing:` in
config), then the registry maps role → model.

```
intent            role         model (you configure)
──────────────    ─────────    ──────────────────────
simple_question → fast       → <models.fast>
code_generation → coding     → <models.coding>
debugging       → reasoning  → <models.reasoning>
architecture    → reasoning  → <models.reasoning>
embedding       → embedding  → <models.embedding>
(unknown)       → default    → <routing.default → role>
```

Both mappings live in config (`configs/default.yaml`, overridable per project):

```yaml
routing:
  simple_question: fast
  code_generation: coding
  debugging: reasoning
  architecture: reasoning
  embedding: embedding
  default: fast
```

Change routing by editing `routing:` — no code changes.

## Health checks

- `cle doctor` reports two model checks:
  - **Models (roles)** — which roles have a model assigned.
  - **Models (installed)** — whether each assigned model is actually installed
    in Ollama (matches implicit `:latest`). Degrades to WARN if the daemon is
    down rather than failing.
- `cle model use <role> <model>` warns if the model isn't installed yet
  (best-effort; the assignment still succeeds).

## Hardware note (RTX 3060 Ti, 8 GB VRAM)

Roles let you use a small/fast model for `fast` and a larger model only for
`coding`/`reasoning`, keeping within VRAM. Don't assume large models fit
comfortably; benchmark (Milestone 12) before committing to a model per role.

## Errors

Resolving a role with no model raises an actionable error:

```
No model configured for role 'coding'.

Try:
  ollama pull <model>
  cle model use coding <model>
```
