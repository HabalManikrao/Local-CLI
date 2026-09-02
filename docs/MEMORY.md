# Project Memory

CLE keeps a **project-scoped** memory in
`<project>/.cle/memory/memory.db`. Knowledge never crosses between unrelated
projects — each project has its own database.

## What it stores

**Entries** (categorized knowledge):

| Kind             | Meaning                                   |
|------------------|-------------------------------------------|
| `decision`       | architecture decision + rationale         |
| `issue`          | known issue / bug                         |
| `convention`     | project convention                        |
| `important_file` | a file worth remembering (+ why)          |
| `agent_decision` | a decision an agent made (+ rationale)    |
| `note`           | free-form note                            |

**Settings** (scalar facts): e.g. `build_command`, `test_command`.

**Sessions / turns**: conversation history for future context.

## Commands

```bash
cle memory                              # summary (counts + settings)
cle memory show                         # list all entries + settings
cle memory show decision                # filter by kind
cle memory add decision "Use SQLite" "Local, simple, no server"
cle memory set test_command "mvn -q test"
cle memory remove 3                     # remove entry #3
cle memory clear                        # wipe (asks to confirm; -y to skip)
```

## Design notes

- Only knowledge **not recoverable from code or git** belongs here (decisions,
  rationale, conventions, commands).
- Build/test commands stored in memory feed the test/debug agents (Milestone 9)
  so they know how to build and test the project.
- Agents record their decisions (`agent_decision`) for an auditable trail
  alongside the session audit logs.
