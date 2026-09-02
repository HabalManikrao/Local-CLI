"""Local audit logging.

Every session gets a JSON audit file under ``logs/<YYYY-MM-DD>/session-NNN.json``
(master prompt §9). This thin implementation records session-level metadata and
an append-only list of events; tool/agent layers add events as they execute.

No secrets are written intentionally. Times are ISO-8601 local timestamps.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_session_path(day_dir: Path) -> Path:
    """Return the next unused ``session-NNN.json`` path within *day_dir*."""
    day_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(day_dir.glob("session-*.json"))
    next_index = len(existing) + 1
    return day_dir / f"session-{next_index:03d}.json"


class AuditLog:
    """An append-only, flush-on-write session audit log."""

    def __init__(self, logs_root: Path, project: str | None, enabled: bool = True):
        self.enabled = enabled
        self.project = project
        started = _now_iso()
        day = started[:10]  # YYYY-MM-DD
        self.path = _next_session_path(logs_root / day) if enabled else None
        self._record: dict[str, Any] = {
            "started_at": started,
            "project": project,
            "events": [],
        }
        if self.enabled:
            self._flush()

    def event(self, kind: str, **fields: Any) -> None:
        """Record an event of *kind* with arbitrary structured *fields*."""
        if not self.enabled:
            return
        self._record["events"].append(
            {"at": _now_iso(), "kind": kind, **fields}
        )
        self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        self.path.write_text(
            json.dumps(self._record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
