"""Project memory facade.

Categorized knowledge (entries) + scalar settings. Convenience wrappers exist
for the common kinds the master prompt calls out (decisions, issues,
conventions, important files, agent decisions, build/test commands).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .database import MemoryDatabase, memory_db_path

# Entry kinds.
DECISION = "decision"
ISSUE = "issue"
CONVENTION = "convention"
IMPORTANT_FILE = "important_file"
AGENT_DECISION = "agent_decision"
NOTE = "note"

KINDS = (DECISION, ISSUE, CONVENTION, IMPORTANT_FILE, AGENT_DECISION, NOTE)

# Well-known settings keys.
BUILD_COMMAND = "build_command"
TEST_COMMAND = "test_command"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Entry:
    id: int
    kind: str
    title: str
    body: str | None
    meta: dict
    created_at: str


class ProjectMemory:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.db = MemoryDatabase(memory_db_path(project_root))

    def close(self) -> None:
        self.db.close()

    # -- entries ------------------------------------------------------------

    def add(self, kind: str, title: str, body: str | None = None,
            meta: dict | None = None) -> int:
        if kind not in KINDS:
            raise ValueError(f"Unknown memory kind: {kind!r}. Valid: {', '.join(KINDS)}")
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO entries(kind, title, body, meta, created_at) "
                "VALUES(?,?,?,?,?)",
                (kind, title, body, json.dumps(meta) if meta else None, _now()),
            )
            return int(cur.lastrowid)

    def entries(self, kind: str | None = None) -> list[Entry]:
        if kind:
            rows = self.db.execute(
                "SELECT * FROM entries WHERE kind = ? ORDER BY id", (kind,)
            ).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM entries ORDER BY kind, id").fetchall()
        return [
            Entry(
                id=r["id"], kind=r["kind"], title=r["title"], body=r["body"],
                meta=json.loads(r["meta"]) if r["meta"] else {},
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def remove(self, entry_id: int) -> bool:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def clear(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM settings")
            conn.execute("DELETE FROM turns")
            conn.execute("DELETE FROM sessions")

    # -- settings -----------------------------------------------------------

    def set_setting(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, _now()),
            )

    def get_setting(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def settings(self) -> dict[str, str]:
        rows = self.db.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # -- convenience --------------------------------------------------------

    def record_decision(self, title: str, detail: str | None = None) -> int:
        return self.add(DECISION, title, detail)

    def record_issue(self, title: str, detail: str | None = None) -> int:
        return self.add(ISSUE, title, detail)

    def add_convention(self, title: str, detail: str | None = None) -> int:
        return self.add(CONVENTION, title, detail)

    def add_important_file(self, path: str, why: str | None = None) -> int:
        return self.add(IMPORTANT_FILE, path, why)

    def record_agent_decision(self, agent: str, decision: str,
                              rationale: str | None = None) -> int:
        return self.add(AGENT_DECISION, decision, rationale, meta={"agent": agent})

    def set_build_command(self, cmd: str) -> None:
        self.set_setting(BUILD_COMMAND, cmd)

    def set_test_command(self, cmd: str) -> None:
        self.set_setting(TEST_COMMAND, cmd)

    # -- summary ------------------------------------------------------------

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for kind in KINDS:
            n = self.db.execute(
                "SELECT COUNT(*) FROM entries WHERE kind = ?", (kind,)
            ).fetchone()[0]
            if n:
                counts[kind] = int(n)
        return counts
