"""Project detection.

A "project" is the directory tree CLE operates on. Detection walks upward from
a starting directory looking for, in priority order:
  1. a ``.cle/`` directory (an initialized CLE project), or
  2. a ``.git`` directory (a git repo we can treat as the project root).

If neither is found, the starting directory itself is used as a loose project
root (commands that require initialization will say so).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import CLE_DIR_NAME


@dataclass
class Project:
    """Resolved project context."""

    root: Path
    is_initialized: bool  # has a .cle/ directory
    is_git_repo: bool

    @property
    def cle_dir(self) -> Path:
        return self.root / CLE_DIR_NAME


def _has_dir(path: Path, name: str) -> bool:
    return (path / name).is_dir()


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk upward from *start* to locate a project root.

    Returns the first ancestor containing ``.cle/`` or ``.git/``; ``None`` if
    the filesystem root is reached without a match.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if _has_dir(candidate, CLE_DIR_NAME) or _has_dir(candidate, ".git"):
            return candidate
    return None


def detect_project(start: Path | None = None) -> Project:
    """Resolve the :class:`Project` for *start* (defaults to cwd).

    Never raises: if nothing is found, the starting directory is returned as an
    uninitialized, non-git project so callers can give tailored guidance.
    """
    start_dir = (start or Path.cwd()).resolve()
    root = find_project_root(start_dir) or start_dir
    return Project(
        root=root,
        is_initialized=_has_dir(root, CLE_DIR_NAME),
        is_git_repo=_has_dir(root, ".git"),
    )


def git_is_available() -> bool:
    """Return True if a ``git`` executable is on PATH."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
            encoding="utf-8",
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False
