"""Permission policy, filesystem confinement, and edit operations."""

from __future__ import annotations

import pytest

from cle.config import Config
from cle.errors import PermissionDeniedError
from cle.safety.permissions import (
    Action,
    Decision,
    PermissionGuard,
    PermissionPolicy,
    approve_all,
    deny_all,
)
from cle.tools.edits import (
    CREATE_FILE,
    DELETE_FILE,
    INSERT_CODE,
    MODIFY_FILE,
    RENAME_FILE,
    REPLACE_BLOCK,
    EditOp,
    EditPlan,
    EditValidationError,
)
from cle.tools.filesystem import FileSystem


def _policy(**kw) -> PermissionPolicy:
    base = dict(require_approval=True, allow_delete=False, allow_network=False, require_git=True)
    base.update(kw)
    return PermissionPolicy(**base)


# -- policy -----------------------------------------------------------------

def test_read_and_search_always_allowed():
    p = _policy()
    assert p.decide(Action.READ_FILE) is Decision.ALLOW
    assert p.decide(Action.SEARCH) is Decision.ALLOW
    assert p.decide(Action.RUN_TESTS) is Decision.ALLOW


def test_write_requires_approval_by_default():
    assert _policy().decide(Action.WRITE_FILE) is Decision.REQUIRE_APPROVAL


def test_write_allowed_when_approval_disabled():
    assert _policy(require_approval=False).decide(Action.WRITE_FILE) is Decision.ALLOW


def test_delete_denied_unless_enabled():
    assert _policy().decide(Action.DELETE_FILE) is Decision.DENY
    assert _policy(allow_delete=True).decide(Action.DELETE_FILE) is Decision.REQUIRE_APPROVAL


def test_network_disabled_by_default():
    assert _policy().decide(Action.NETWORK) is Decision.DENY
    assert _policy(allow_network=True).decide(Action.NETWORK) is Decision.ALLOW


def test_guard_blocks_unapproved_write():
    guard = PermissionGuard(_policy(), approver=deny_all)
    with pytest.raises(PermissionDeniedError):
        guard.check(Action.WRITE_FILE, "write x")


def test_guard_allows_approved_write():
    guard = PermissionGuard(_policy(), approver=approve_all)
    guard.check(Action.WRITE_FILE, "write x")  # no raise


def test_policy_from_config():
    cfg = Config({"safety": {"require_approval": False, "allow_delete": True}}, None)
    p = PermissionPolicy.from_config(cfg)
    assert p.require_approval is False and p.allow_delete is True


# -- filesystem confinement -------------------------------------------------

def test_filesystem_refuses_escape(tmp_path):
    fs = FileSystem(tmp_path, PermissionGuard(_policy(require_approval=False)))
    with pytest.raises(PermissionDeniedError):
        fs.write_file("../evil.txt", "x")


def test_filesystem_write_and_read(tmp_path):
    fs = FileSystem(tmp_path, PermissionGuard(_policy(require_approval=False)))
    fs.write_file("sub/a.txt", "hello")
    assert fs.read_file("sub/a.txt") == "hello"


# -- edit operations --------------------------------------------------------

def _fs(tmp_path):
    return FileSystem(tmp_path, PermissionGuard(_policy(require_approval=False, allow_delete=True)))


def test_create_and_modify(tmp_path):
    fs = _fs(tmp_path)
    plan = EditPlan([EditOp(CREATE_FILE, "a.txt", content="one\n")])
    assert plan.validate(tmp_path) == []
    plan.apply(fs, tmp_path)
    assert (tmp_path / "a.txt").read_text() == "one\n"

    plan2 = EditPlan([EditOp(MODIFY_FILE, "a.txt", content="two\n")])
    plan2.apply(fs, tmp_path)
    assert (tmp_path / "a.txt").read_text() == "two\n"


def test_create_existing_is_invalid(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    plan = EditPlan([EditOp(CREATE_FILE, "a.txt", content="y")])
    assert any("already exists" in e for e in plan.validate(tmp_path))


def test_insert_code(tmp_path):
    (tmp_path / "a.txt").write_text("l1\nl3\n", encoding="utf-8")
    fs = _fs(tmp_path)
    EditPlan([EditOp(INSERT_CODE, "a.txt", content="l2", at_line=2)]).apply(fs, tmp_path)
    assert (tmp_path / "a.txt").read_text() == "l1\nl2\nl3\n"


def test_replace_block_unique(tmp_path):
    (tmp_path / "a.txt").write_text("keep\nOLD\nkeep\n", encoding="utf-8")
    fs = _fs(tmp_path)
    EditPlan([EditOp(REPLACE_BLOCK, "a.txt", find="OLD", replace="NEW")]).apply(fs, tmp_path)
    assert "NEW" in (tmp_path / "a.txt").read_text()


def test_replace_block_ambiguous_is_invalid(tmp_path):
    (tmp_path / "a.txt").write_text("dup\ndup\n", encoding="utf-8")
    plan = EditPlan([EditOp(REPLACE_BLOCK, "a.txt", find="dup", replace="x")])
    assert any("ambiguous" in e for e in plan.validate(tmp_path))


def test_rename(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    fs = _fs(tmp_path)
    EditPlan([EditOp(RENAME_FILE, "a.txt", new_path="b.txt")]).apply(fs, tmp_path)
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text() == "x"


def test_apply_refuses_invalid_plan(tmp_path):
    fs = _fs(tmp_path)
    plan = EditPlan([EditOp(MODIFY_FILE, "missing.txt", content="x")])
    with pytest.raises(EditValidationError):
        plan.apply(fs, tmp_path)


def test_delete_blocked_when_policy_forbids(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    fs = FileSystem(tmp_path, PermissionGuard(_policy(require_approval=False, allow_delete=False)))
    with pytest.raises(PermissionDeniedError):
        EditPlan([EditOp(DELETE_FILE, "a.txt")]).apply(fs, tmp_path)


def test_preview_shows_diff(tmp_path):
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    plan = EditPlan([EditOp(MODIFY_FILE, "a.txt", content="new\n")])
    preview = plan.preview(tmp_path)
    assert "-old" in preview and "+new" in preview
