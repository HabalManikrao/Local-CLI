"""Debug agent.

Given failing tests, it retrieves the relevant LOCAL source, asks the reasoning
model to diagnose the root cause, and can frame a fix request for the coding
agent. Diagnosis makes no changes; fixing goes through the normal
plan→approve→apply path.
"""

from __future__ import annotations

from ..context.manager import ContextManager
from ..tools.test_runner import TestFailure, TestRunResult
from .base import BaseAgent

_SYSTEM = (
    "You are a senior engineer debugging failing tests in the user's LOCAL "
    "project. Diagnose the most likely root cause from the evidence provided. "
    "Cite file:line where possible. Be concise and concrete."
)


class DebugAgent(BaseAgent):
    def diagnose(self, result: TestRunResult, max_failures: int = 5) -> str:
        failures = result.failures[:max_failures]
        context_block = self._context_for(failures)
        failure_text = "\n".join(
            f"- {f.name}"
            + (f" ({f.file}:{f.line})" if f.file and f.line else
               f" ({f.file})" if f.file else "")
            + (f": {f.message}" if f.message else "")
            for f in failures
        ) or "(no structured failures parsed)"

        # Tail of raw output helps when parsing missed something.
        tail = "\n".join(result.output.splitlines()[-40:])
        prompt = (
            f"The test command `{' '.join(result.command)}` failed "
            f"(exit {result.returncode}).\n\n"
            f"Parsed failures:\n{failure_text}\n\n"
            + (f"Relevant LOCAL source:\n{context_block}\n\n" if context_block else "")
            + f"Test output (tail):\n```\n{tail}\n```\n\n"
            "Explain the most likely root cause and the specific fix."
        )
        model = self.router.model_for_intent("debugging")
        return self.provider.generate(model, prompt, system=_SYSTEM).text

    def fix_request(self, result: TestRunResult, max_failures: int = 5) -> str:
        """Build a natural-language request for the coding agent to fix tests."""
        failures = result.failures[:max_failures]
        lines = [
            f"- {f.name}" + (f" at {f.file}:{f.line}" if f.file else "")
            + (f" — {f.message}" if f.message else "")
            for f in failures
        ]
        tail = "\n".join(result.output.splitlines()[-30:])
        return (
            "Fix the following failing tests by changing the source (not by "
            "weakening the tests unless they are clearly wrong):\n"
            + "\n".join(lines)
            + f"\n\nTest output (tail):\n{tail}"
        )

    def _context_for(self, failures: list[TestFailure]) -> str:
        engine = self.context_engine()
        if engine is None:
            return ""
        try:
            query = " ".join(
                (f.file or "") + " " + f.name.replace("::", " ") for f in failures
            )
            items = engine.retrieve(query)
            block, _ = ContextManager(self.config).build_block(items)
            return block
        finally:
            engine.index.close()
