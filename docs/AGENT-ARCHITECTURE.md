# Agent Architecture

Agents plan and reason with the model + context engine, then act **only**
through the permission-guarded tool layer. They never write files before
approval.

## Shared base (`agents/base.py`)

- `extract_json(text)` — robust extraction of a single JSON object from model
  output (handles ```json fences, prose wrappers, embedded objects).
- `BaseAgent` — holds the dependency graph (provider, router, registry, config,
  root) and builds a `ContextEngine` when the project is indexed.

## Coding agent (`agents/coding.py`)

Workflow (§M7):

```
Understand → Inspect → Retrieve context → Plan → Show plan → Approval
→ Edit → Test → Review
```

Split into two phases so nothing is written before approval:

- **`plan(request)`** — retrieves LOCAL context, prompts the coding model for a
  strict JSON plan, converts proposed `changes` into validated `EditOp`s, and
  returns a `CodingPlan`. **Pure reasoning — zero writes.**
- **`apply(plan, fs)`** — applies the (already-approved) plan through the
  permission-guarded `FileSystem`. Refuses to apply a plan with validation
  errors.

### The plan the agent emits

`CodingPlan` carries exactly the fields §M7 requires:

- Goal
- Files inspected
- Reasoning summary
- Proposed changes (structured `EditOp`s + per-change explanations)
- Expected impact
- Tests to run
- Risks

### `cle code` flow

```
cle code "<request>"
  → agent.plan()                 (no writes)
  → render Goal/Files/Reasoning/Changes/Impact/Tests/Risks
  → render unified diff preview
  → if validation errors: stop
  → approval prompt (once, whole batch)   [--yes to skip, --no-apply to stop here]
  → git checkpoint (if a repo)            (safety, before editing)
  → agent.apply() via guarded FileSystem
  → report results; suggest `cle diff` / `cle rollback` / `cle test`
```

The batch approval builds a guard with an "approve-all" approver **for the
approved writes only** — policy DENY still holds (e.g. deletion stays disabled
unless `allow_delete`).

## Model routing per agent

| Agent phase        | Intent            | Role       |
|--------------------|-------------------|------------|
| Coding             | `code_generation` | coding     |
| Explain / architecture | `architecture`| reasoning  |
| (Debugging — M9)   | `debugging`       | reasoning  |

Roles resolve to models via config; no model names are hard-coded.

## Later agents

Debugging, testing, refactoring, research, and documentation agents (Milestones
9–10) follow the same plan-then-guarded-act pattern and reuse `BaseAgent`,
the context engine, and the edit/permission tools.
