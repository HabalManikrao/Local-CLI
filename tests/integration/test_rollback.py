"""cle rollback command: no-checkpoint, abort, success, and restore-failure.

The underlying GitRepo.restore_checkpoint happy path is covered in test_git.py;
this covers the command's branches — the safety net for autonomous edits.
"""

from __future__ import annotations

import subprocess

import pytest

from cle.cli import commands, ui
from cle.errors import GitError
from cle.tools.checkpoints import CheckpointStore
from cle.tools.git import GitRepo
from tests.conftest import make_context


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, encoding="utf-8")


@pytest.fixture
def ctx_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    ctx = make_context(tmp_path)   # creates .cle/
    return ctx, tmp_path


def _make_checkpoint(root) -> None:
    g = GitRepo(root)
    (root / "a.txt").write_text("checkpointed\n", encoding="utf-8")
    sha = g.create_checkpoint()
    CheckpointStore(root).add(sha, "master", "cp",
                              list(g.status().untracked_files))


@pytest.mark.integration
def test_cmd_rollback_no_checkpoint(ctx_repo, capsys):
    ctx, _ = ctx_repo
    code = commands.cmd_rollback(ctx, checkpoint_id=None, yes=True)
    assert code == 1
    assert "No checkpoint" in capsys.readouterr().err


@pytest.mark.integration
def test_cmd_rollback_restores_tracked(ctx_repo):
    ctx, root = ctx_repo
    _make_checkpoint(root)
    (root / "a.txt").write_text("later edit\n", encoding="utf-8")
    code = commands.cmd_rollback(ctx, checkpoint_id=None, yes=True)
    assert code == 0
    assert (root / "a.txt").read_text() == "checkpointed\n"


@pytest.mark.integration
def test_cmd_rollback_aborts_on_no(ctx_repo, monkeypatch):
    ctx, root = ctx_repo
    _make_checkpoint(root)
    (root / "a.txt").write_text("later edit\n", encoding="utf-8")
    monkeypatch.setattr(ui.console, "input", lambda *a, **k: "n")
    code = commands.cmd_rollback(ctx, checkpoint_id=None, yes=False)
    assert code == 0
    assert (root / "a.txt").read_text() == "later edit\n"   # untouched


@pytest.mark.integration
def test_cmd_rollback_restore_failure(ctx_repo, monkeypatch, capsys):
    ctx, root = ctx_repo
    _make_checkpoint(root)

    def boom(self, sha):
        raise GitError("restore failed", remedy="check git state")

    monkeypatch.setattr(GitRepo, "restore_checkpoint", boom)
    code = commands.cmd_rollback(ctx, checkpoint_id=None, yes=True)
    assert code == 1
    assert "restore failed" in capsys.readouterr().err
