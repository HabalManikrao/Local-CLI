"""Test runner tool.

Detects the project's build/test system (Maven, Gradle, or Python/pytest),
runs the tests through the permission layer, and parses failures into a
structured form the debug agent can act on.

Failure parsing is heuristic and tool-specific; it favors useful recall of the
failing test name + location over perfect precision.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..safety.permissions import Action, PermissionGuard


class BuildSystem(str, Enum):
    MAVEN = "maven"
    GRADLE = "gradle"
    PYTHON = "python"
    UNKNOWN = "unknown"


@dataclass
class TestFailure:
    name: str
    file: str | None = None
    line: int | None = None
    message: str = ""


@dataclass
class TestRunResult:
    system: BuildSystem
    command: list[str]
    returncode: int
    passed: bool
    output: str
    failures: list[TestFailure] = field(default_factory=list)
    error: str | None = None       # set when the runner could not execute


def detect_build_system(root: Path) -> tuple[BuildSystem, list[str]]:
    """Detect the build system and its default test command."""
    if (root / "pom.xml").exists():
        return BuildSystem.MAVEN, ["mvn", "-q", "-B", "test"]
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        if (root / "gradlew.bat").exists():
            return BuildSystem.GRADLE, ["cmd", "/c", "gradlew.bat", "test"]
        if (root / "gradlew").exists():
            return BuildSystem.GRADLE, ["./gradlew", "test"]
        return BuildSystem.GRADLE, ["gradle", "test"]
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() \
            or (root / "tests").is_dir():
        # Use the current interpreter so pytest is found without relying on a
        # console script being on PATH.
        return BuildSystem.PYTHON, [sys.executable, "-m", "pytest"]
    return BuildSystem.UNKNOWN, []


def run_tests(
    root: Path,
    *,
    command: list[str] | None = None,
    guard: PermissionGuard | None = None,
    timeout: int = 600,
) -> TestRunResult:
    """Run the project's tests and return a structured result."""
    if command:
        system, _ = detect_build_system(root)
        cmd = command
    else:
        system, cmd = detect_build_system(root)

    if not cmd:
        return TestRunResult(
            system=BuildSystem.UNKNOWN, command=[], returncode=-1, passed=False,
            output="", error="Could not detect a build/test system.",
        )

    if guard is not None:
        guard.check(Action.RUN_TESTS, f"run tests: {' '.join(cmd)}")

    exe = shutil.which(cmd[0]) if cmd[0] not in ("cmd", "./gradlew") else cmd[0]
    if cmd[0] not in ("cmd", "./gradlew") and exe is None:
        return TestRunResult(
            system=system, command=cmd, returncode=-1, passed=False, output="",
            error=f"'{cmd[0]}' is not on PATH. Install it or set a test command "
                  f"in memory (cle memory set test_command \"...\").",
        )

    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return TestRunResult(
            system=system, command=cmd, returncode=-1, passed=False, output="",
            error=f"Failed to run tests: {exc}",
        )

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    failures = parse_failures(output, system)
    return TestRunResult(
        system=system, command=cmd, returncode=proc.returncode,
        passed=proc.returncode == 0, output=output, failures=failures,
    )


# -- failure parsing --------------------------------------------------------

_PYTEST_FAILED = re.compile(r"^FAILED\s+(\S+?)(?:\[.*?\])?\s*(?:-\s*(.*))?$", re.MULTILINE)
_PYTEST_LOC = re.compile(r"^(.*?):(\d+): in ", re.MULTILINE)
_JAVA_FAIL = re.compile(r"^\s*(?:\[ERROR\]\s*)?(\w+)\((\S+?)\).*<<< (?:FAILURE|ERROR)!", re.MULTILINE)
_JAVA_AT = re.compile(r"at\s+[\w.$]+\(([\w$]+\.java):(\d+)\)")


def parse_failures(output: str, system: BuildSystem) -> list[TestFailure]:
    if system == BuildSystem.PYTHON:
        return _parse_pytest(output)
    if system in (BuildSystem.MAVEN, BuildSystem.GRADLE):
        return _parse_java(output)
    return []


def _parse_pytest(output: str) -> list[TestFailure]:
    failures: list[TestFailure] = []
    for m in _PYTEST_FAILED.finditer(output):
        target = m.group(1)
        message = (m.group(2) or "").strip()
        file = target.split("::", 1)[0] if "::" in target else None
        failures.append(TestFailure(name=target, file=file, message=message))
    return failures


def _parse_java(output: str) -> list[TestFailure]:
    failures: list[TestFailure] = []
    for m in _JAVA_FAIL.finditer(output):
        method, cls = m.group(1), m.group(2)
        # Look for a source location near this failure.
        tail = output[m.end() : m.end() + 800]
        loc = _JAVA_AT.search(tail)
        file = loc.group(1) if loc else None
        line = int(loc.group(2)) if loc else None
        failures.append(TestFailure(
            name=f"{cls}.{method}", file=file, line=line, message="test failed",
        ))
    return failures
