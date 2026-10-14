"""Repository scanning and index building.

Walks a project tree, detects language, parses symbols/imports, and stores
everything in the SQLite index. Provides a query facade used by later
milestones (search, retrieval, agents).

Indexing is a full rebuild per run (simple and correct); incremental indexing
via the stored file hash is a future optimization noted in the audit.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..logging_setup import get_logger
from .database import IndexDatabase
from .symbols import detect_language, parse_source

log = get_logger("indexing")

# Directories never worth indexing.
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".cle", ".venv", "venv", "env", "__pycache__", "node_modules",
    "target", "build", "dist", ".gradle", ".idea", ".mvn", "out", "bin",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
# Files above this size are recorded but not parsed for symbols.
MAX_PARSE_BYTES = 2_000_000


def index_db_path(project_root: Path) -> Path:
    return project_root / ".cle" / "index" / "index.db"


def iter_source_files(
    root: Path, exclude_dirs: set[str] | None = None
) -> Iterator[Path]:
    """Yield files under *root*, skipping excluded directories."""
    excludes = exclude_dirs or DEFAULT_EXCLUDE_DIRS
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in excludes for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


@dataclass
class IndexStats:
    files: int = 0
    parsed: int = 0
    symbols: int = 0
    imports: int = 0
    languages: dict[str, int] = field(default_factory=dict)


class IndexBuilder:
    def __init__(self, root: Path, db: IndexDatabase):
        self.root = root
        self.db = db

    def build(self, on_file: Callable[[Path], None] | None = None) -> IndexStats:
        self.db.clear()
        stats = IndexStats(languages={})
        with self.db.transaction() as conn:
            for path in iter_source_files(self.root):
                try:
                    raw = path.read_bytes()
                except OSError:
                    continue
                rel = path.relative_to(self.root).as_posix()
                language = detect_language(path)
                text: str | None = None
                if len(raw) <= MAX_PARSE_BYTES:
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = None  # binary/undecodable → file-level only

                lines = text.count("\n") + 1 if text else 0
                file_hash = hashlib.sha1(raw).hexdigest()
                cur = conn.execute(
                    "INSERT INTO files(path, language, size_bytes, lines, mtime, hash) "
                    "VALUES(?,?,?,?,?,?)",
                    (rel, language, len(raw), lines, path.stat().st_mtime, file_hash),
                )
                file_id = cur.lastrowid
                stats.files += 1
                if language:
                    stats.languages[language] = stats.languages.get(language, 0) + 1

                if text is not None and language in ("java", "python"):
                    parsed = parse_source(path, text)
                    stats.parsed += 1
                    for s in parsed.symbols:
                        conn.execute(
                            "INSERT INTO symbols"
                            "(file_id, kind, name, parent, line_start, line_end, signature, extra) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (file_id, s.kind, s.name, s.parent, s.line_start,
                             s.line_end, s.signature, _json(s.extra)),
                        )
                        stats.symbols += 1
                    for imp in parsed.imports:
                        conn.execute(
                            "INSERT INTO imports(file_id, target, line) VALUES(?,?,?)",
                            (file_id, imp.target, imp.line),
                        )
                        stats.imports += 1
                if on_file:
                    on_file(path)
        self.db.set_meta("root", str(self.root))
        return stats


def _json(data: dict) -> str | None:
    import json
    return json.dumps(data) if data else None


class RepositoryIndex:
    """Read/query facade over the index database."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.db = IndexDatabase(index_db_path(project_root))

    # -- lifecycle ----------------------------------------------------------

    def rebuild(self, on_file: Callable[[Path], None] | None = None) -> IndexStats:
        return IndexBuilder(self.project_root, self.db).build(on_file)

    def close(self) -> None:
        self.db.close()

    # -- queries ------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        def n(sql: str) -> int:
            return int(self.db.execute(sql).fetchone()[0])
        return {
            "files": n("SELECT COUNT(*) FROM files"),
            "symbols": n("SELECT COUNT(*) FROM symbols"),
            "imports": n("SELECT COUNT(*) FROM imports"),
        }

    def languages(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT language, COUNT(*) c FROM files "
            "WHERE language IS NOT NULL GROUP BY language ORDER BY c DESC"
        ).fetchall()
        return {r["language"]: r["c"] for r in rows}

    def find_symbols(self, name: str, kind: str | None = None) -> list[dict]:
        sql = (
            "SELECT s.*, f.path AS file_path FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE s.name = ?"
        )
        params: tuple = (name,)
        if kind:
            sql += " AND s.kind = ?"
            params += (kind,)
        sql += " ORDER BY f.path, s.line_start"
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def symbols_in_file(self, rel_path: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT s.* FROM symbols s JOIN files f ON f.id = s.file_id "
            "WHERE f.path = ? ORDER BY s.line_start",
            (rel_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def is_built(self) -> bool:
        return index_db_path(self.project_root).exists() and \
            self.counts()["files"] > 0
