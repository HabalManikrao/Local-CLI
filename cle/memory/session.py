"""Session/conversation memory.

Records conversation turns per session so past interactions can inform future
context. Shares the memory database with :class:`ProjectMemory`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .database import MemoryDatabase, memory_db_path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SessionMemory:
    def __init__(self, project_root: Path, db: MemoryDatabase | None = None):
        self.db = db or MemoryDatabase(memory_db_path(project_root))

    def start(self, label: str | None = None) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO sessions(started_at, label) VALUES(?, ?)",
                (_now(), label),
            )
            assert cur.lastrowid is not None  # guaranteed after INSERT
            return cur.lastrowid

    def add_turn(self, session_id: int, role: str, content: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO turns(session_id, role, content, at) VALUES(?,?,?,?)",
                (session_id, role, content, _now()),
            )

    def turns(self, session_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content, at FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_sessions(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, started_at, label FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
