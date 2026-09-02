"""Git tool.

Thin wrapper over the git CLI (no GitPython dependency — matches the audit's
"drive existing tools" posture). Provides state inspection, diffs, and
non-destructive checkpoints via ``git stash create`` so the agent can snapshot
before editing and roll back if the user rejects changes.

Checkpoint scope note: ``git stash create`` snapshots tracked (and modified)
files. Brand-new untracked files are recorded by name at checkpoint time so
rollback can report — but never silently delete — files added since.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import GitError


@dataclass
class GitStatus:
    branch: str
    clean: bool
    changed_files: list[str]
    untracked_files: list[str]


class GitRepo:
    def __init__(self, root: Path):
        self.root = root

    # -- low-level ----------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> str:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True, encoding="utf-8", errors="replace",
            )
        except OSError as exc:
            raise GitError(
                "git executable not found.",
                remedy="Install Git and ensure it is on PATH.",
            ) from exc
        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout

    # -- state --------------------------------------------------------------

    def is_repo(self) -> bool:
        try:
            out = self._git("rev-parse", "--is-inside-work-tree", check=False)
        except GitError:
            return False
        return out.strip() == "true"

    def current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def status(self) -> GitStatus:
        out = self._git("status", "--porcelain")
        changed: list[str] = []
        untracked: list[str] = []
        for line in out.splitlines():
            if not line:
                continue
            code, path = line[:2], line[3:]
            if code == "??":
                untracked.append(path)
            else:
                changed.append(path)
        try:
            branch = self.current_branch()
        except GitError:
            branch = "(unknown)"
        return GitStatus(
            branch=branch,
            clean=not changed and not untracked,
            changed_files=changed,
            untracked_files=untracked,
        )

    def has_uncommitted_changes(self) -> bool:
        return not self.status().clean

    def diff(self, *paths: str) -> str:
        # Include unstaged changes for tracked files.
        return self._git("diff", "--", *paths) if paths else self._git("diff")

    # -- checkpoints --------------------------------------------------------

    def create_checkpoint(self) -> str:
        """Return a snapshot commit SHA for the current working tree.

        Uses ``git stash create`` (non-destructive: does not touch the working
        tree, index, or stash list). For a clean tree it returns HEAD.
        """
        sha = self._git("stash", "create", "cle-checkpoint").strip()
        if not sha:
            sha = self._git("rev-parse", "HEAD").strip()
        return sha

    def restore_checkpoint(self, sha: str) -> None:
        """Restore tracked files to snapshot *sha* (working tree only)."""
        # Validate the object exists first for a clean error.
        self._git("cat-file", "-e", sha)
        self._git("checkout", sha, "--", ".")

    def commit_all(self, message: str) -> str:
        """Stage everything and commit. Returns the new commit SHA."""
        self._git("add", "-A")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "HEAD").strip()
