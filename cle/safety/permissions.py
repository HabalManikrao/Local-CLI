"""Permission / safety policy.

Central gate for side-effecting actions. Defaults (master prompt §8):

    READ FILE / SEARCH / GIT STATUS / RUN TESTS   -> ALLOWED
    WRITE FILE / DELETE FILE / SHELL / GIT COMMIT -> APPROVAL
    NETWORK                                        -> DISABLED

The policy is derived from ``safety.*`` config. Every mutating tool asks the
:class:`PermissionGuard` before acting; the guard consults the policy and, when
approval is required, an injected approver callback (interactive prompt in the
CLI, auto-decision in tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ..config import Config
from ..errors import PermissionDeniedError


class Action(str, Enum):
    READ_FILE = "read_file"
    SEARCH = "search"
    GIT_STATUS = "git_status"
    RUN_TESTS = "run_tests"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    SHELL_COMMAND = "shell_command"
    GIT_COMMIT = "git_commit"
    NETWORK = "network"


class Decision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


# Approver: given a human-readable description, return True to approve.
Approver = Callable[[str], bool]


def deny_all(_description: str) -> bool:
    return False


def approve_all(_description: str) -> bool:
    return True


@dataclass
class PermissionPolicy:
    require_approval: bool = True
    allow_delete: bool = False
    allow_network: bool = False
    require_git: bool = True

    @classmethod
    def from_config(cls, config: Config) -> "PermissionPolicy":
        return cls(
            require_approval=bool(config.get("safety.require_approval", True)),
            allow_delete=bool(config.get("safety.allow_delete", False)),
            allow_network=bool(config.get("safety.allow_network", False)),
            require_git=bool(config.get("safety.require_git", True)),
        )

    _ALWAYS_ALLOWED = {
        Action.READ_FILE, Action.SEARCH, Action.GIT_STATUS, Action.RUN_TESTS,
    }

    def decide(self, action: Action) -> Decision:
        if action is Action.NETWORK:
            return Decision.ALLOW if self.allow_network else Decision.DENY
        if action is Action.DELETE_FILE and not self.allow_delete:
            # Deletion disabled by default; even approval can't override policy.
            return Decision.DENY
        if action in self._ALWAYS_ALLOWED:
            return Decision.ALLOW
        # Mutating actions: approval when required, else allowed.
        return Decision.REQUIRE_APPROVAL if self.require_approval else Decision.ALLOW


class PermissionGuard:
    def __init__(self, policy: PermissionPolicy, approver: Approver = deny_all):
        self.policy = policy
        self.approver = approver

    def check(self, action: Action, description: str) -> None:
        """Raise :class:`PermissionDeniedError` unless *action* is permitted."""
        decision = self.policy.decide(action)
        if decision is Decision.ALLOW:
            return
        if decision is Decision.DENY:
            raise PermissionDeniedError(
                f"Action '{action.value}' is disabled by safety policy: {description}",
                remedy=_deny_remedy(action),
            )
        # REQUIRE_APPROVAL
        if not self.approver(description):
            raise PermissionDeniedError(
                f"Action '{action.value}' was not approved: {description}",
                remedy="Re-run and approve when prompted, or adjust safety settings.",
            )


def _deny_remedy(action: Action) -> str | None:
    if action is Action.DELETE_FILE:
        return "Deletion is disabled. Enable with safety.allow_delete: true (use with care)."
    if action is Action.NETWORK:
        return "Network is disabled. CLE runs offline by design."
    return None
