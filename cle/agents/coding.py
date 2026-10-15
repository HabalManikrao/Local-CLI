"""Coding agent.

Workflow (master prompt §M7):

    Understand → Inspect → Retrieve context → Plan → Show plan → Approval
    → Edit → Test → Review

The agent is split into :meth:`plan` (pure reasoning; no writes) and
:meth:`apply` (guarded writes) so that **nothing is modified before approval**.
The command layer shows the plan + diff, asks once, then calls ``apply``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..context.manager import ContextManager
from ..tools.edits import (
    OP_TYPES,
    EditOp,
    EditPlan,
)
from ..tools.filesystem import FileSystem
from .base import AgentError, BaseAgent, extract_json

_SYSTEM = (
    "You are a precise senior software engineer working on the user's LOCAL "
    "codebase. You propose concrete, minimal changes. You MUST respond with a "
    "single JSON object and nothing else."
)

_SCHEMA_HINT = """\
Respond with JSON of exactly this shape:
{
  "goal": "one sentence restating the objective",
  "reasoning": "short summary of your approach",
  "expected_impact": "what changes in behaviour",
  "risks": ["..."],
  "tests_to_run": ["command or test name", "..."],
  "changes": [
    {"op": "MODIFY_FILE", "path": "rel/path", "content": "FULL new file contents", "explanation": "why"},
    {"op": "CREATE_FILE", "path": "rel/path", "content": "file contents", "explanation": "why"},
    {"op": "REPLACE_BLOCK", "path": "rel/path", "find": "exact unique text", "replace": "new text", "explanation": "why"},
    {"op": "INSERT_CODE", "path": "rel/path", "at_line": 42, "content": "code", "explanation": "why"},
    {"op": "RENAME_FILE", "path": "rel/old", "new_path": "rel/new", "explanation": "why"}
  ]
}
Rules: use REPLACE_BLOCK with a unique 'find' for small edits; use MODIFY_FILE
with COMPLETE contents for large rewrites. Keep changes minimal and correct.
"""


def _as_str_list(value: object) -> list[str]:
    """Coerce a model field to a list of strings.

    Real models sometimes return a bare string where a list is expected
    (``"risks": "may break login"``); iterating that char-by-char produced
    garbled output. A string becomes a single-element list; a list is mapped
    to str; anything else yields an empty list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


@dataclass
class CodingPlan:
    goal: str
    reasoning: str
    expected_impact: str
    risks: list[str]
    tests_to_run: list[str]
    files_inspected: list[str]
    changes: list[dict]                 # raw change dicts (with explanations)
    edit_plan: EditPlan
    validation_errors: list[str] = field(default_factory=list)


class CodingAgent(BaseAgent):
    def plan(self, request: str, model: str | None = None) -> CodingPlan:
        model = model or self.router.model_for_intent("code_generation")

        # Inspect + retrieve context (LOCAL evidence).
        files_inspected: list[str] = []
        context_block = ""
        engine = self.context_engine()
        if engine is not None:
            try:
                items = engine.retrieve(request)
                files_inspected = sorted({it.path for it in items})
                block, _ = ContextManager(self.config).build_block(items)
                context_block = block
            finally:
                engine.index.close()

        prompt = (
            f"Task: {request}\n\n"
            + (f"Relevant LOCAL context:\n{context_block}\n\n" if context_block else "")
            + _SCHEMA_HINT
        )
        result = self.provider.generate(model, prompt, system=_SYSTEM)
        data = extract_json(result.text)

        changes = data.get("changes") or []
        if not isinstance(changes, list):
            raise AgentError(
                "Model returned 'changes' in an unexpected shape (expected a list).",
                remedy="Retry the request; ask the model to follow the JSON schema.",
            )
        edit_ops = [self._to_edit_op(c) for c in changes]
        edit_plan = EditPlan(edit_ops)
        errors = edit_plan.validate(self.root)

        return CodingPlan(
            goal=str(data.get("goal", request)),
            reasoning=str(data.get("reasoning", "")),
            expected_impact=str(data.get("expected_impact", "")),
            risks=_as_str_list(data.get("risks")),
            tests_to_run=_as_str_list(data.get("tests_to_run")),
            files_inspected=files_inspected,
            changes=changes,
            edit_plan=edit_plan,
            validation_errors=errors,
        )

    def apply(self, plan: CodingPlan, fs: FileSystem) -> list[str]:
        """Apply an approved plan through the guarded filesystem."""
        if plan.validation_errors:
            raise AgentError(
                "Refusing to apply: the plan has validation errors:\n- "
                + "\n- ".join(plan.validation_errors),
                remedy="Ask the agent to revise, or edit the plan.",
            )
        return plan.edit_plan.apply(fs, self.root)

    @staticmethod
    def _to_edit_op(change: dict) -> EditOp:
        if not isinstance(change, dict):
            raise AgentError(
                f"Model proposed a change that is not an object: {change!r}",
                remedy="Retry the request; each change must be a JSON object.",
            )
        op = str(change.get("op", "")).upper()
        if op not in OP_TYPES:
            raise AgentError(
                f"Model proposed an unknown edit operation: {op!r}",
                remedy="Retry the request.",
            )
        # Real models often emit numbers as strings ("at_line": "42"); coerce so
        # the downstream edit math doesn't TypeError on str - int.
        at_line = change.get("at_line")
        if at_line is not None:
            try:
                at_line = int(at_line)
            except (TypeError, ValueError) as exc:
                raise AgentError(
                    f"Model proposed a non-integer at_line: {at_line!r}",
                    remedy="Retry the request.",
                ) from exc
        return EditOp(
            op=op,
            path=str(change.get("path", "")),
            content=change.get("content"),
            new_path=change.get("new_path"),
            find=change.get("find"),
            replace=change.get("replace"),
            at_line=at_line,
        )
