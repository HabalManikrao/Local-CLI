"""Finding model shared by the analyzers."""

from __future__ import annotations

from dataclasses import dataclass

# Severity ordering for sorting/reporting.
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}


@dataclass
class Finding:
    severity: str        # HIGH | MEDIUM | LOW | INFO
    category: str        # short slug, e.g. "brittle-wait"
    title: str
    file: str            # project-relative posix path
    line: int
    recommendation: str
    snippet: str = ""

    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), self.file, self.line)
