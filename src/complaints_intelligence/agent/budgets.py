"""Bounds on an agent run.

Invariant 4: the agent is read-only and bounded — capped steps and revision
loops. A bound that crashes the run is not a usable bound, so exhaustion is a
condition the graph handles, not an exception that escapes to the caller: the
run finishes with whatever it has and records why it stopped.

The counters are here rather than inside the nodes so that "how much did this
run cost" is answerable from one object, and so a node cannot forget to
decrement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from complaints_intelligence.config import BudgetConfig
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)


@dataclass
class BudgetLedger:
    """Mutable spend against a run's budget."""

    config: BudgetConfig
    llm_calls: int = 0
    tool_calls: int = 0
    revisions: int = 0
    #: Human-readable notes about anything that was cut short.
    notes: list[str] = field(default_factory=list)

    def spend_llm(self, node: str) -> None:
        """Record one model call, raising if the budget is exhausted."""
        if self.llm_calls >= self.config.max_llm_calls:
            msg = (
                f"LLM call budget exhausted at {self.config.max_llm_calls} "
                f"(node {node!r})"
            )
            raise BudgetExceededError(msg)
        self.llm_calls += 1

    def spend_tool(self, node: str, tool: str) -> None:
        """Record one tool call, raising if the budget is exhausted."""
        if self.tool_calls >= self.config.max_tool_calls:
            msg = (
                f"tool call budget exhausted at {self.config.max_tool_calls} "
                f"(node {node!r}, tool {tool!r})"
            )
            raise BudgetExceededError(msg)
        self.tool_calls += 1

    def may_revise(self) -> bool:
        """Whether another revision round is permitted."""
        return self.revisions < self.config.max_revisions

    def spend_revision(self) -> None:
        self.revisions += 1

    def note(self, message: str) -> None:
        """Record a degradation. Surfaced in the trace and the report."""
        log.warning("run_degraded", reason=message)
        self.notes.append(message)

    def summary(self) -> dict[str, int]:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "revisions": self.revisions,
        }
