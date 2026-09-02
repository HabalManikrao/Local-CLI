"""Index build + query integration tests against a temp project."""

from __future__ import annotations

from pathlib import Path

import pytest

from cle.indexing.repository import RepositoryIndex, iter_source_files


def _make_project(root: Path) -> None:
    (root / ".cle").mkdir()
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "target").mkdir()  # should be excluded
    (root / "src" / "main" / "java" / "Login.java").write_text(
        "package a;\n"
        "import java.util.List;\n"
        "public class Login {\n"
        "  private int count;\n"
        "  public void run() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "util.py").write_text(
        "def go():\n    return 1\n", encoding="utf-8"
    )
    (root / "target" / "Ignored.java").write_text(
        "public class Ignored {}\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# hi\n", encoding="utf-8")


def test_iter_source_files_excludes_build_dirs(tmp_path):
    _make_project(tmp_path)
    files = {p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)}
    assert "util.py" in files
    assert "src/main/java/Login.java" in files
    assert "target/Ignored.java" not in files


@pytest.mark.integration
def test_build_and_query(tmp_path):
    _make_project(tmp_path)
    index = RepositoryIndex(tmp_path)
    try:
        stats = index.rebuild()
        assert stats.files >= 3
        assert stats.languages["java"] == 1

        counts = index.counts()
        assert counts["symbols"] > 0

        found = index.find_symbols("run", kind="method")
        assert found and found[0]["file_path"] == "src/main/java/Login.java"

        syms = index.symbols_in_file("src/main/java/Login.java")
        kinds = {s["kind"] for s in syms}
        assert {"package", "class", "method", "field"} <= kinds

        assert index.is_built() is True
    finally:
        index.close()


@pytest.mark.integration
def test_rebuild_is_idempotent(tmp_path):
    _make_project(tmp_path)
    index = RepositoryIndex(tmp_path)
    try:
        first = index.rebuild().files
        second = index.rebuild().files  # clears then rebuilds — no duplication
        assert first == second
        assert index.counts()["files"] == first
    finally:
        index.close()
