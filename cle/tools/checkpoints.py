"""Checkpoint registry.

Persists snapshot references (from :meth:`GitRepo.create_checkpoint`) so
``cle rollback`` can restore a prior working-tree state. Stored as JSON under
``.cle/checkpoints/checkpoints.json``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Checkpoint:
    id: int
    sha: str
    branch: str
    label: str
    at: str
    untracked: list[str]


class CheckpointStore:
    def __init__(self, project_root: Path):
        self.path = project_root / ".cle" / "checkpoints" / "checkpoints.json"

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, data: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, sha: str, branch: str, label: str, untracked: list[str]) -> Checkpoint:
        data = self._load()
        cp = Checkpoint(
            id=len(data) + 1, sha=sha, branch=branch, label=label,
            at=datetime.now().isoformat(timespec="seconds"), untracked=untracked,
        )
        data.append(asdict(cp))
        self._save(data)
        return cp

    def list(self) -> list[Checkpoint]:
        return [Checkpoint(**d) for d in self._load()]

    def latest(self) -> Checkpoint | None:
        cps = self.list()
        return cps[-1] if cps else None

    def get(self, checkpoint_id: int) -> Checkpoint | None:
        for cp in self.list():
            if cp.id == checkpoint_id:
                return cp
        return None
