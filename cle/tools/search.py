"""Exact text search.

Prefers ripgrep (fast, respects .gitignore) and falls back to a pure-Python
scan when ``rg`` is not on PATH, so search always works offline. Returns
structured matches (file / line / column / text) carrying LOCAL evidence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..evidence import EvidenceSource
from ..indexing.repository import DEFAULT_EXCLUDE_DIRS


@dataclass
class SearchMatch:
    path: str          # project-relative posix path
    line: int
    column: int
    text: str
    source: EvidenceSource = EvidenceSource.LOCAL


def ripgrep_available() -> bool:
    return shutil.which("rg") is not None


def search(
    root: Path,
    pattern: str,
    *,
    max_results: int = 200,
    ignore_case: bool = False,
    fixed_string: bool = False,
) -> list[SearchMatch]:
    """Search *pattern* under *root*, returning up to *max_results* matches."""
    if ripgrep_available():
        return _ripgrep_search(
            root, pattern, max_results, ignore_case, fixed_string
        )
    return _python_search(root, pattern, max_results, ignore_case, fixed_string)


def _ripgrep_search(
    root: Path, pattern: str, max_results: int, ignore_case: bool, fixed: bool
) -> list[SearchMatch]:
    cmd = ["rg", "--json", "--max-count", str(max_results)]
    if ignore_case:
        cmd.append("-i")
    if fixed:
        cmd.append("-F")
    cmd += [pattern, str(root)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return _python_search(root, pattern, max_results, ignore_case, fixed)

    matches: list[SearchMatch] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        abs_path = Path(data["path"]["text"])
        try:
            rel = abs_path.relative_to(root).as_posix()
        except ValueError:
            rel = abs_path.as_posix()
        submatches = data.get("submatches", [{}])
        col = (submatches[0].get("start", 0) + 1) if submatches else 1
        matches.append(SearchMatch(
            path=rel,
            line=data["line_number"],
            column=col,
            text=data["lines"]["text"].rstrip("\n"),
        ))
        if len(matches) >= max_results:
            break
    return matches


def _python_search(
    root: Path, pattern: str, max_results: int, ignore_case: bool, fixed: bool
) -> list[SearchMatch]:
    import re

    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(re.escape(pattern) if fixed else pattern, flags)
    matches: list[SearchMatch] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in DEFAULT_EXCLUDE_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = regex.search(line)
            if m:
                matches.append(SearchMatch(
                    path=path.relative_to(root).as_posix(),
                    line=i, column=m.start() + 1, text=line,
                ))
                if len(matches) >= max_results:
                    return matches
    return matches
