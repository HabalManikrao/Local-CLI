"""Shared scanning helpers for the analyzers.

Provides comment-safe line iteration over Java files so rules don't fire on
commented-out code or string contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..indexing.repository import iter_source_files
from ..indexing.symbols import _strip_comments, detect_language
from .findings import Finding


@dataclass
class JavaFile:
    rel: str
    raw_lines: list[str]      # original source lines
    clean_lines: list[str]    # comment/string content blanked, same line count
    clean_text: str


def iter_java_files(root: Path) -> list[JavaFile]:
    """Return comment-stripped views of every Java file under *root*."""
    files: list[JavaFile] = []
    for path in iter_source_files(root):
        if detect_language(path) != "java":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        clean = _strip_comments(text)
        files.append(JavaFile(
            rel=path.relative_to(root).as_posix(),
            raw_lines=text.splitlines(),
            clean_lines=clean.splitlines(),
            clean_text=clean,
        ))
    return files


@dataclass
class LineRule:
    pattern: re.Pattern
    severity: str
    category: str
    title: str
    recommendation: str


def scan_line_rules(jf: JavaFile, rules: list[LineRule]) -> list[Finding]:
    """Apply per-line regex *rules* to a Java file (comment-safe)."""
    findings: list[Finding] = []
    for idx, clean in enumerate(jf.clean_lines):
        if not clean.strip():
            continue
        for rule in rules:
            if rule.pattern.search(clean):
                raw = jf.raw_lines[idx].strip() if idx < len(jf.raw_lines) else clean.strip()
                findings.append(Finding(
                    severity=rule.severity, category=rule.category,
                    title=rule.title, file=jf.rel, line=idx + 1,
                    recommendation=rule.recommendation, snippet=raw[:160],
                ))
    return findings


def line_of_offset(text: str, offset: int) -> int:
    """1-based line number for a character *offset* into *text*."""
    return text.count("\n", 0, offset) + 1

