"""Architecture decision records (ADRs) over project memory.

A thin, typed convenience layer on top of :class:`ProjectMemory` for recording
and listing architecture decisions with their rationale — the kind of context
that is not recoverable from code or git history.
"""

from __future__ import annotations

from dataclasses import dataclass

from .project import DECISION, ProjectMemory


@dataclass
class Decision:
    id: int
    title: str
    rationale: str | None
    created_at: str


def record(memory: ProjectMemory, title: str, rationale: str | None = None) -> int:
    """Record an architecture decision; returns its id."""
    return memory.record_decision(title, rationale)


def list_decisions(memory: ProjectMemory) -> list[Decision]:
    return [
        Decision(id=e.id, title=e.title, rationale=e.body, created_at=e.created_at)
        for e in memory.entries(DECISION)
    ]
