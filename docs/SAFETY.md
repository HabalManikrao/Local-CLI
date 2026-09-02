# Safety Model

CLE mediates every side-effecting action. LLMs never touch the filesystem,
shell, or git directly — they propose; the safety layer disposes.

## Permission defaults (§8)

| Action        | Default        |
|---------------|----------------|
| Read file     | ALLOWED        |
| Search        | ALLOWED        |
| Git status    | ALLOWED        |
| Run tests     | ALLOWED        |
| Write file    | APPROVAL       |
| Delete file   | APPROVAL (and disabled unless `allow_delete`) |
| Shell command | APPROVAL       |
| Git commit    | APPROVAL       |
| Network       | DISABLED       |

Configured under `safety:`:

```yaml
safety:
  require_approval: true
  allow_delete: false
  allow_network: false
  require_git: true
```

- `PermissionPolicy.decide(action)` → ALLOW / REQUIRE_APPROVAL / DENY.
- `PermissionGuard.check(action, description)` enforces it, calling an
  **approver** callback for approval-required actions (interactive prompt in the
  CLI; auto-decision in tests). Deletion is DENY unless `allow_delete` is on —
  approval alone cannot override policy.

## Filesystem confinement

`FileSystem` resolves every path under the project root and refuses to operate
outside it. All writes/deletes/renames pass through the guard.

## Structured edits

Edits are explicit operations — `CREATE_FILE`, `MODIFY_FILE`, `DELETE_FILE`,
`RENAME_FILE`, `INSERT_CODE`, `REPLACE_BLOCK` — that are:

1. **Validated** before anything is written (target exists/doesn't, `REPLACE_BLOCK`
   `find` text is present and **unique**, rename destination free, ...). A plan
   with any error is refused wholesale — never partially applied.
2. **Previewed** as a unified diff.
3. **Applied** only through the permission-guarded `FileSystem`.

Never silently overwrites unrelated changes: `MODIFY_FILE` replaces a known
file, `REPLACE_BLOCK` refuses ambiguous matches, and `CREATE_FILE` refuses to
clobber an existing file.

## Git checkpoints & rollback

- `cle checkpoint "<label>"` — non-destructive snapshot via `git stash create`
  (does not touch working tree, index, or stash list). Clean tree → HEAD.
  Recorded in `.cle/checkpoints/checkpoints.json`.
- `cle rollback [id]` — restores tracked files to a checkpoint (latest by
  default), after confirmation.
- `cle diff` — working-tree diff + status.

**Scope limit (documented, not a bug):** checkpoints snapshot tracked/modified
files. Brand-new untracked files created since a checkpoint are **reported on
rollback, never auto-deleted** — CLE does not delete files without approval.

`require_git: true` means edit-capable flows expect a git repo so a checkpoint
can be taken before changes.

## Audit

Every session writes `logs/<date>/session-NNN.json` recording requests, models,
tools executed, files touched, and results. No secrets are written intentionally.
