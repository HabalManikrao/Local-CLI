"""Structured edit operations.

Edits are represented as validated operations, previewed as a unified diff, and
applied atomically-ish through the :class:`FileSystem` tool (which enforces
permissions). Operations (master prompt §8):

    CREATE_FILE  MODIFY_FILE  DELETE_FILE  RENAME_FILE  INSERT_CODE  REPLACE_BLOCK

Changes are validated *before* anything is written; a plan with any validation
error is refused wholesale.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from ..errors import CleError
from .filesystem import FileSystem

CREATE_FILE = "CREATE_FILE"
MODIFY_FILE = "MODIFY_FILE"
DELETE_FILE = "DELETE_FILE"
RENAME_FILE = "RENAME_FILE"
INSERT_CODE = "INSERT_CODE"
REPLACE_BLOCK = "REPLACE_BLOCK"

OP_TYPES = {CREATE_FILE, MODIFY_FILE, DELETE_FILE, RENAME_FILE, INSERT_CODE, REPLACE_BLOCK}


@dataclass
class EditOp:
    op: str
    path: str
    content: str | None = None       # CREATE/MODIFY/INSERT/(REPLACE new)
    new_path: str | None = None      # RENAME
    find: str | None = None          # REPLACE_BLOCK
    replace: str | None = None       # REPLACE_BLOCK
    at_line: int | None = None       # INSERT_CODE (1-based; None/EOF => append)


class EditValidationError(CleError):
    pass


def _read(root: Path, rel: str) -> str | None:
    p = (root / rel)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _resulting_content(root: Path, op: EditOp) -> str | None:
    """Compute the post-edit content for a single-file op (for preview/validate).

    Returns None for pure-deletion ops.
    """
    current = _read(root, op.path)
    if op.op == CREATE_FILE:
        return op.content or ""
    if op.op == MODIFY_FILE:
        return op.content or ""
    if op.op == DELETE_FILE:
        return None
    if op.op == INSERT_CODE:
        lines = (current or "").splitlines(keepends=True)
        insert = op.content or ""
        if not insert.endswith("\n"):
            insert += "\n"
        idx = len(lines) if op.at_line is None else max(0, op.at_line - 1)
        idx = min(idx, len(lines))
        lines[idx:idx] = [insert]
        return "".join(lines)
    if op.op == REPLACE_BLOCK:
        text = current or ""
        return text.replace(op.find or "", op.replace or "", 1)
    return current


class EditPlan:
    def __init__(self, ops: list[EditOp]):
        self.ops = ops

    # -- validation ---------------------------------------------------------

    def validate(self, root: Path) -> list[str]:
        errors: list[str] = []
        for i, op in enumerate(self.ops):
            tag = f"op[{i}] {op.op} {op.path}"
            if op.op not in OP_TYPES:
                errors.append(f"{tag}: unknown operation")
                continue
            exists = (root / op.path).exists()
            if op.op == CREATE_FILE:
                if exists:
                    errors.append(f"{tag}: file already exists")
                if op.content is None:
                    errors.append(f"{tag}: missing content")
            elif op.op in (MODIFY_FILE, INSERT_CODE, REPLACE_BLOCK, DELETE_FILE):
                if not exists:
                    errors.append(f"{tag}: file does not exist")
            if op.op == MODIFY_FILE and op.content is None:
                errors.append(f"{tag}: missing content")
            if op.op == REPLACE_BLOCK:
                if not op.find:
                    errors.append(f"{tag}: missing 'find' text")
                else:
                    text = _read(root, op.path) or ""
                    occurrences = text.count(op.find)
                    if occurrences == 0:
                        errors.append(f"{tag}: 'find' text not present")
                    elif occurrences > 1:
                        errors.append(
                            f"{tag}: 'find' text is ambiguous ({occurrences} matches); "
                            "make it unique"
                        )
            if op.op == RENAME_FILE:
                if not exists:
                    errors.append(f"{tag}: source does not exist")
                if not op.new_path:
                    errors.append(f"{tag}: missing new_path")
                elif (root / op.new_path).exists():
                    errors.append(f"{tag}: destination already exists: {op.new_path}")
        return errors

    # -- preview ------------------------------------------------------------

    def preview(self, root: Path) -> str:
        chunks: list[str] = []
        for op in self.ops:
            if op.op == RENAME_FILE:
                chunks.append(f"rename: {op.path} -> {op.new_path}")
                continue
            if op.op == DELETE_FILE:
                chunks.append(f"delete: {op.path}")
                continue
            before = (_read(root, op.path) or "")
            after = _resulting_content(root, op) or ""
            diff = difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{op.path}", tofile=f"b/{op.path}",
            )
            body = "".join(diff)
            chunks.append(body or f"(no textual change) {op.path}")
        return "\n".join(chunks)

    def summary(self) -> list[str]:
        out = []
        for op in self.ops:
            if op.op == RENAME_FILE:
                out.append(f"{op.op}: {op.path} -> {op.new_path}")
            else:
                out.append(f"{op.op}: {op.path}")
        return out

    # -- apply --------------------------------------------------------------

    def apply(self, fs: FileSystem, root: Path) -> list[str]:
        """Apply all ops (after validation). Returns per-op result strings.

        Validation is re-run first; a plan that fails validation is refused so
        we never partially apply an invalid plan.
        """
        errors = self.validate(root)
        if errors:
            raise EditValidationError(
                "Edit plan failed validation:\n- " + "\n- ".join(errors),
                remedy="Fix the operations and retry.",
            )
        results: list[str] = []
        for op in self.ops:
            if op.op in (CREATE_FILE, MODIFY_FILE, INSERT_CODE, REPLACE_BLOCK):
                new_content = _resulting_content(root, op) or ""
                fs.write_file(op.path, new_content)
                results.append(f"wrote {op.path}")
            elif op.op == DELETE_FILE:
                fs.delete_file(op.path)
                results.append(f"deleted {op.path}")
            elif op.op == RENAME_FILE:
                fs.rename_file(op.path, op.new_path)  # type: ignore[arg-type]
                results.append(f"renamed {op.path} -> {op.new_path}")
        return results
