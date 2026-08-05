"""The agent's tools: read-only, parameterised, budgeted.

This module is the entire surface between the agent and the data. What the
agent cannot do through it — compute a statistic, write anything, change the
taxonomy, publish, reach the network — is absent from the interface rather than
forbidden by instruction, which is the only prohibition that survives an
adversarial input.
"""

from __future__ import annotations

from complaints_intelligence.agent.state import BudgetLedger
from complaints_intelligence.inputs import ComplaintEnvelope, Precedent
from complaints_intelligence.store import Store


class ToolBelt:
    """The bound set of tools for one run.

    Holds the store and the budget so a node calls a tool with the arguments it
    cares about and nothing else, and cannot forget to spend budget.
    """

    def __init__(self, store: Store, ledger: BudgetLedger) -> None:
        self._store = store
        self._ledger = ledger
        self._node = "unknown"
        self.calls = 0

    def entering(self, node: str) -> None:
        """Record which node is running, for budget attribution."""
        self._node = node

    def get_exemplars(
        self,
        *,
        query_text: str,
        week: str,
        category: str | None = None,
        theme_id: str | None = None,
    ) -> tuple[ComplaintEnvelope, ...]:
        """Retrieve representative complaints for a week.

        The limit is the configured per-finding maximum: an unbounded retrieval
        would let one investigation consume the whole context window and starve
        the rest of the report.
        """
        self._ledger.spend_tool(self._node, "get_exemplars")
        self.calls += 1
        return self._store.exemplars(
            query_text=query_text,
            week=week,
            category=category,
            theme_id=theme_id,
            limit=self._ledger.config.max_exemplars_per_finding,
        )

    def get_precedent(
        self, *, query_text: str, category: str | None = None
    ) -> tuple[Precedent, ...]:
        """Retrieve comparable closed complaints with their resolution notes.

        ``category=None`` is the remediation node's widened second pass: a
        precedent from a neighbouring category may still transfer.
        """
        self._ledger.spend_tool(self._node, "get_precedent")
        self.calls += 1
        return self._store.search_precedents(
            query_text=query_text,
            category=category,
            limit=self._ledger.config.max_precedents_per_finding,
        )
