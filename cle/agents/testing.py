"""Test agent — runs the project's tests and reports structured results."""

from __future__ import annotations

from pathlib import Path

from ..safety.permissions import PermissionGuard
from ..tools.test_runner import TestRunResult, run_tests


class TestAgent:
    def __init__(self, root: Path, guard: PermissionGuard | None = None):
        self.root = root
        self.guard = guard

    def run(self, command: list[str] | None = None) -> TestRunResult:
        return run_tests(self.root, command=command, guard=self.guard)
