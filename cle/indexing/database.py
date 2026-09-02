"""SQLite storage for the repository index.

The database lives at ``<project>/.cle/index/index.db``. Schema is created on
demand and versioned via a ``meta`` table so future migrations are possible.
All access goes through :class:`IndexDatabase`; nothing else opens the file.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import CleError

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY,
    path       TEXT UNIQUE NOT NULL,
    language   TEXT,
    size_bytes INTEGER,
    lines      INTEGER,
    mtime      REAL,
    hash       TEXT
);

CREATE TABLE IF NOT EXISTS symbols (
    id         INTEGER PRIMARY KEY,
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    parent     TEXT,
    line_start INTEGER,
    line_end   INTEGER,
    signature  TEXT,
    extra      TEXT
);

CREATE TABLE IF NOT EXISTS imports (
    id      INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target  TEXT NOT NULL,
    line    INTEGER
);

CREATE TABLE IF NOT EXISTS embeddings (
    id      INTEGER PRIMARY KEY,
    path    TEXT NOT NULL,
    start   INTEGER NOT NULL,
    end     INTEGER NOT NULL,
    text    TEXT NOT NULL,
    model   TEXT NOT NULL,
    dim     INTEGER NOT NULL,
    vector  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_files_language ON files(language);
"""


class IndexDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(db_path))
        except sqlite3.Error as exc:  # pragma: no cover
            raise CleError(f"Could not open index database: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        cur = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        if row is None:
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

    def clear(self) -> None:
        """Remove all indexed data (files/symbols/imports) but keep the schema."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM imports")
            conn.execute("DELETE FROM files")

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        self._conn.close()
