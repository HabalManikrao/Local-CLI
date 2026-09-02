from pathlib import Path

from cle.project import detect_project, find_project_root


def test_detect_uninitialized(tmp_path: Path):
    p = detect_project(tmp_path)
    assert p.root == tmp_path.resolve()
    assert p.is_initialized is False
    assert p.is_git_repo is False


def test_detect_initialized_cle(tmp_path: Path):
    (tmp_path / ".cle").mkdir()
    p = detect_project(tmp_path)
    assert p.is_initialized is True
    assert p.cle_dir == tmp_path.resolve() / ".cle"


def test_detect_git_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    p = detect_project(tmp_path)
    assert p.is_git_repo is True


def test_find_root_walks_upward(tmp_path: Path):
    (tmp_path / ".cle").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path.resolve()


def test_find_root_returns_none_when_absent(tmp_path: Path):
    nested = tmp_path / "x" / "y"
    nested.mkdir(parents=True)
    # No .cle or .git anywhere under tmp_path; may still find one in real
    # ancestors, so only assert it does not point inside tmp_path.
    root = find_project_root(nested)
    assert root is None or tmp_path.resolve() not in root.parents
