"""SQLite storage for project memory.

Two tables cover the requirement:

- ``entries``  — categorized knowledge (decisions, issues, conventions,
  important files, agent decisions, free notes).
- ``settings`` — scalar project facts (build command, test command, ...).

Sessions/conversations live in their own tables (see :mod:`cle.memory.session`).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    meta       TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    label      TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_kind ON entries(kind);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
"""


class MemoryDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        if self._conn.execute(
            "SELECT 1 FROM meta WHERE key='schema_version'"
        ).fetchone() is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def close(self) -> None:
        self._conn.close()


def memory_db_path(project_root: Path) -> Path:
    return project_root / ".cle" / "memory" / "memory.db"
