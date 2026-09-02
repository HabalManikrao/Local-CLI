"""Winium automation-framework analysis.

Detects Winium/WinAppDriver patterns and common automation smells: fixed
sleeps, brittle absolute XPath, poor driver lifecycle, and duplicated locators.
Evidence-backed; makes no changes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .base import JavaFile, LineRule, iter_java_files, scan_line_rules
from .findings import Finding

_LINE_RULES = [
    LineRule(
        re.compile(r"\bThread\.sleep\s*\("), "HIGH", "brittle-wait",
        "Thread.sleep() detected",
        "Replace fixed sleep with an explicit wait (WebDriverWait/until).",
    ),
    LineRule(
        re.compile(r"getScreenshotAs\s*\("), "INFO", "screenshot",
        "Screenshot capture",
        "Ensure screenshots are captured on failure for diagnostics.",
    ),
    LineRule(
        re.compile(r"By\.accessibilityId|findElementByAccessibilityId"),
        "INFO", "accessibility-id",
        "Accessibility ID locator (good practice)",
        "Prefer accessibility IDs over XPath where possible.",
    ),
]

# Driver init and lifecycle.
_DRIVER_INIT = re.compile(r"new\s+WiniumDriver\s*\(")
_DRIVER_TEARDOWN = re.compile(r"\.(quit|close)\s*\(")

# Locators.
_ABS_XPATH = re.compile(r"""By\.xpath\s*\(\s*["'](/{1,2}[^"']*)["']""")
_ANY_LOCATOR = re.compile(
    r"""By\.(?:xpath|id|name|className|tagName)\s*\(\s*["']([^"']+)["']"""
)


def _driver_findings(files: list[JavaFile]) -> list[Finding]:
    findings: list[Finding] = []
    project_has_teardown = any(_DRIVER_TEARDOWN.search(jf.clean_text) for jf in files)
    for jf in files:
        for idx, clean in enumerate(jf.clean_lines):
            if _DRIVER_INIT.search(clean):
                sev, rec, title = (
                    ("INFO", "Driver is initialized; lifecycle looks managed.",
                     "WiniumDriver initialization")
                    if project_has_teardown else
                    ("MEDIUM", "No driver.quit()/close() found — ensure the driver "
                     "is torn down (e.g. in @After/@AfterClass).",
                     "WiniumDriver initialized without visible teardown")
                )
                findings.append(Finding(
                    severity=sev, category="driver-lifecycle", title=title,
                    file=jf.rel, line=idx + 1, recommendation=rec,
                    snippet=jf.raw_lines[idx].strip()[:160] if idx < len(jf.raw_lines) else "",
                ))
    return findings


def _abs_xpath_findings(files: list[JavaFile]) -> list[Finding]:
    findings: list[Finding] = []
    for jf in files:
        for idx, clean in enumerate(jf.clean_lines):
            if _ABS_XPATH.search(clean):
                findings.append(Finding(
                    severity="MEDIUM", category="brittle-locator",
                    title="Absolute/near-absolute XPath locator",
                    file=jf.rel, line=idx + 1,
                    recommendation="Prefer accessibility IDs or relative locators; "
                                   "absolute XPath is brittle to UI changes.",
                    snippet=jf.raw_lines[idx].strip()[:160] if idx < len(jf.raw_lines) else "",
                ))
    return findings


def _duplicated_locator_findings(files: list[JavaFile]) -> list[Finding]:
    # literal -> list of (file, line)
    occurrences: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for jf in files:
        for idx, clean in enumerate(jf.clean_lines):
            for m in _ANY_LOCATOR.finditer(clean):
                occurrences[m.group(1)].append((jf.rel, idx + 1))

    findings: list[Finding] = []
    for literal, locs in occurrences.items():
        if len(locs) > 1:
            file, line = locs[0]
            where = ", ".join(f"{f}:{ln}" for f, ln in locs[:6])
            findings.append(Finding(
                severity="MEDIUM", category="duplicated-locator",
                title=f"Locator duplicated {len(locs)}x: {literal[:40]}",
                file=file, line=line,
                recommendation="Centralize the locator (page object / locator "
                               f"constants). Seen at: {where}.",
            ))
    return findings


def analyze_winium(root: Path) -> list[Finding]:
    files = iter_java_files(root)
    findings: list[Finding] = []
    for jf in files:
        findings.extend(scan_line_rules(jf, _LINE_RULES))
    findings.extend(_driver_findings(files))
    findings.extend(_abs_xpath_findings(files))
    findings.extend(_duplicated_locator_findings(files))
    findings.sort(key=lambda f: f.sort_key())
    return findings
