"""Filesystem tool.

The only sanctioned path to mutate files. Every write/delete/rename goes through
the :class:`~cle.safety.permissions.PermissionGuard`, so the permission and
audit layers mediate all side effects. Paths are confined to the project root.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import PermissionDeniedError, ProjectError
from ..safety.permissions import Action, PermissionGuard


class FileSystem:
    def __init__(self, root: Path, guard: PermissionGuard):
        self.root = root.resolve()
        self.guard = guard

    def _resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        # Confinement: never operate outside the project root.
        if self.root not in target.parents and target != self.root:
            raise PermissionDeniedError(
                f"Refusing to operate outside the project root: {rel}",
                remedy="Use a path inside the project.",
            )
        return target

    def read_file(self, rel: str) -> str:
        self.guard.check(Action.READ_FILE, f"read {rel}")
        path = self._resolve(rel)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectError(f"Could not read {rel}: {exc}") from exc

    def write_file(self, rel: str, content: str) -> None:
        self.guard.check(Action.WRITE_FILE, f"write {rel}")
        path = self._resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_file(self, rel: str) -> None:
        self.guard.check(Action.DELETE_FILE, f"delete {rel}")
        path = self._resolve(rel)
        try:
            path.unlink()
        except OSError as exc:
            raise ProjectError(f"Could not delete {rel}: {exc}") from exc

    def rename_file(self, rel: str, new_rel: str) -> None:
        # Rename = write new + remove old; require write permission (and delete
        # if the policy treats moves as deletions — here write covers the move).
        self.guard.check(Action.WRITE_FILE, f"rename {rel} -> {new_rel}")
        src = self._resolve(rel)
        dst = self._resolve(new_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            src.replace(dst)
        except OSError as exc:
            raise ProjectError(f"Could not rename {rel} -> {new_rel}: {exc}") from exc

    def exists(self, rel: str) -> bool:
        return self._resolve(rel).exists()
