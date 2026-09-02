"""General Java quality analysis.

Rule-based, evidence-backed findings. Makes no changes.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..indexing.repository import RepositoryIndex
from .base import JavaFile, LineRule, iter_java_files, line_of_offset, scan_line_rules
from .findings import Finding

_LINE_RULES = [
    LineRule(
        re.compile(r"\bprintStackTrace\s*\("), "LOW", "exception-handling",
        "printStackTrace() used",
        "Replace printStackTrace with structured logging.",
    ),
    LineRule(
        re.compile(r"\bSystem\.(out|err)\.print"), "LOW", "logging",
        "System.out/err used for logging",
        "Use a logging framework (SLF4J/Log4j) instead of System.out/err.",
    ),
    LineRule(
        re.compile(r"\bThread\.sleep\s*\("), "MEDIUM", "unnecessary-sleep",
        "Thread.sleep() detected",
        "Avoid fixed sleeps; use explicit waits/conditions.",
    ),
    LineRule(
        re.compile(r"//\s*(TODO|FIXME)|/\*\s*(TODO|FIXME)"), "INFO", "todo",
        "TODO/FIXME marker",
        "Track and resolve the outstanding work.",
    ),
]

_EMPTY_CATCH = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}", re.DOTALL)


def _empty_catch_findings(jf: JavaFile) -> list[Finding]:
    findings: list[Finding] = []
    for m in _EMPTY_CATCH.finditer(jf.clean_text):
        line = line_of_offset(jf.clean_text, m.start())
        findings.append(Finding(
            severity="MEDIUM", category="exception-handling",
            title="Empty catch block", file=jf.rel, line=line,
            recommendation="Handle or log the exception; do not swallow it silently.",
            snippet=jf.raw_lines[line - 1].strip()[:160] if line - 1 < len(jf.raw_lines) else "",
        ))
    return findings


def _long_method_findings(root: Path, threshold: int = 80) -> list[Finding]:
    index = RepositoryIndex(root)
    if not index.is_built():
        index.close()
        return []
    findings: list[Finding] = []
    try:
        rows = index.db.execute(
            "SELECT s.name, s.line_start, s.line_end, f.path "
            "FROM symbols s JOIN files f ON f.id = s.file_id "
            "WHERE s.kind IN ('method','constructor') AND s.line_end IS NOT NULL"
        ).fetchall()
        for r in rows:
            span = (r["line_end"] or r["line_start"]) - r["line_start"]
            if span > threshold:
                findings.append(Finding(
                    severity="LOW", category="long-method",
                    title=f"Long method '{r['name']}' ({span} lines)",
                    file=r["path"], line=r["line_start"],
                    recommendation="Consider decomposing into smaller methods.",
                ))
    finally:
        index.close()
    return findings


def analyze_java(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for jf in iter_java_files(root):
        findings.extend(scan_line_rules(jf, _LINE_RULES))
        findings.extend(_empty_catch_findings(jf))
    findings.extend(_long_method_findings(root))
    findings.sort(key=lambda f: f.sort_key())
    return findings
