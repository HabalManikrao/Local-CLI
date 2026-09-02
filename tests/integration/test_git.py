"""GitRepo + checkpoint/rollback against a real temporary git repo."""

from __future__ import annotations

import subprocess

import pytest

from cle.tools.checkpoints import CheckpointStore
from cle.tools.git import GitRepo


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


@pytest.mark.integration
def test_is_repo_and_status(repo):
    g = GitRepo(repo)
    assert g.is_repo() is True
    assert g.status().clean is True
    (repo / "a.txt").write_text("v2\n", encoding="utf-8")
    st = g.status()
    assert st.clean is False
    assert "a.txt" in st.changed_files


@pytest.mark.integration
def test_not_a_repo(tmp_path):
    assert GitRepo(tmp_path).is_repo() is False


@pytest.mark.integration
def test_checkpoint_and_rollback_restores_tracked(repo):
    g = GitRepo(repo)
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    sha = g.create_checkpoint()          # snapshot the dirty state
    assert sha

    (repo / "a.txt").write_text("more-dirty\n", encoding="utf-8")
    g.restore_checkpoint(sha)            # back to "dirty"
    assert (repo / "a.txt").read_text() == "dirty\n"


@pytest.mark.integration
def test_checkpoint_clean_tree_uses_head(repo):
    g = GitRepo(repo)
    sha = g.create_checkpoint()
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, encoding="utf-8",
    ).stdout.strip()
    assert sha == head


@pytest.mark.integration
def test_checkpoint_store_roundtrip(repo):
    store = CheckpointStore(repo)
    cp = store.add("deadbeef", "master", "before edits", [])
    assert cp.id == 1
    assert store.latest().sha == "deadbeef"
    assert store.get(1).label == "before edits"
