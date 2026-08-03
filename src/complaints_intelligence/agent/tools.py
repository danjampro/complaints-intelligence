"""The agent's tools. Read-only, parameterised, budgeted, traced.

This module is the entire surface between the agent and the data. Three tools,
each taking validated arguments:

- ``query_metrics`` — read an allowlisted view. The view name is a ``Literal``,
  so an unlisted view is a type error at the call site and a ``ToolContractError``
  at runtime. There is no free-form SQL anywhere in the reachable graph.
- ``get_exemplars`` — retrieve complaints by similarity, scoped to a week.
- ``get_resolutions`` — retrieve resolution notes from closed complaints.

What the agent cannot do through this surface: compute a statistic, write
anything, modify the taxonomy, publish, or reach the network. Those are absent
from the interface rather than forbidden by instruction, which is the only
form of prohibition that survives an adversarial input.

Every call is counted against the budget and appended to the trace before the
result is returned, so a run's cost and its evidence trail cannot diverge.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from complaints_intelligence.agent.budgets import BudgetLedger
from complaints_intelligence.domain.complaint import ComplaintEnvelope, ResolutionNote
from complaints_intelligence.domain.trace import ToolCall
from complaints_intelligence.errors import ToolContractError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.store.duckdb_store import DuckDBStore

log = get_logger(__name__)

#: Views the agent may read. Adding one is a deliberate act with a diff.
MetricView = Literal[
    "v_weekly_category_counts",
    "v_weekly_category_channel_counts",
    "v_sentiment_by_channel_week",
    "v_sentiment_by_week",
    "v_health_indicators",
    "v_candidate_themes",
]

ALLOWED_VIEWS: frozenset[str] = frozenset(get_args(MetricView))

#: Filter columns the agent may use. Narrower than what the views expose:
#: filtering on a measure column would let the agent select rows by their
#: values, which is a way of computing a statistic one query at a time.
ALLOWED_FILTERS: frozenset[str] = frozenset(
    {"week", "category", "channel", "theme_id", "taxonomy_version"}
)


class ToolBelt:
    """The bound set of tools for one run.

    Holds the store, the budget and the trace so a node calls a tool with the
    arguments it cares about and nothing else. A node that had to remember to
    record its own trace entry is a node that will eventually forget.
    """

    def __init__(self, store: DuckDBStore, ledger: BudgetLedger) -> None:
        self._store = store
        self._ledger = ledger
        self._calls: list[ToolCall] = []
        self._node = "unknown"

    def entering(self, node: str) -> None:
        """Record which node is running, for trace attribution."""
        self._node = node

    @property
    def calls(self) -> tuple[ToolCall, ...]:
        return tuple(self._calls)

    def _record(
        self,
        tool: str,
        arguments: dict[str, str | int | float | None],
        result_count: int,
        fact_ids: tuple[str, ...] = (),
    ) -> None:
        self._calls.append(
            ToolCall(
                sequence=len(self._calls),
                node=self._node,
                tool=tool,
                arguments=arguments,
                result_count=result_count,
                fact_ids_returned=fact_ids,
            )
        )

    # -- tools ------------------------------------------------------------

    def query_metrics(
        self, view: str, filters: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Read one allowlisted view with equality filters.

        Both the view name and every filter column are checked against
        allowlists. The failure is a ``ToolContractError`` rather than an
        empty result, because a silently-empty result would let a malformed
        or malicious query look like a legitimate finding of nothing.
        """
        self._ledger.spend_tool(self._node, "query_metrics")

        if view not in ALLOWED_VIEWS:
            msg = (
                f"view {view!r} is not available to the agent. "
                f"Allowed: {sorted(ALLOWED_VIEWS)}"
            )
            raise ToolContractError(msg)

        filters = filters or {}
        illegal = set(filters) - ALLOWED_FILTERS
        if illegal:
            msg = (
                f"filter columns {sorted(illegal)} are not permitted. "
                f"Allowed: {sorted(ALLOWED_FILTERS)}"
            )
            raise ToolContractError(msg)

        rows = self._store.query_view(view, dict(filters))
        self._record(
            "query_metrics",
            {"view": view, **{f"filter.{k}": v for k, v in filters.items()}},
            len(rows),
        )
        return rows

    def get_exemplars(
        self,
        *,
        query_text: str,
        week: str,
        category: str | None = None,
        theme_id: str | None = None,
        limit: int = 6,
    ) -> tuple[ComplaintEnvelope, ...]:
        """Retrieve representative complaints.

        ``limit`` is clamped to the configured per-finding maximum. An
        unbounded retrieval would let one investigation consume the whole
        context window and starve the rest of the report.
        """
        self._ledger.spend_tool(self._node, "get_exemplars")
        capped = min(limit, self._ledger.config.max_exemplars_per_finding)

        results = self._store.exemplars(
            query_text=query_text,
            week=week,
            category=category,
            theme_id=theme_id,
            limit=capped,
        )
        self._record(
            "get_exemplars",
            {
                "week": week,
                "category": category,
                "theme_id": theme_id,
                "limit": capped,
                "query_chars": len(query_text),
            },
            len(results),
        )
        return results

    def get_resolutions(
        self,
        *,
        query_text: str,
        category: str | None = None,
        limit: int = 6,
    ) -> tuple[ResolutionNote, ...]:
        """Retrieve resolution notes from comparable closed complaints."""
        self._ledger.spend_tool(self._node, "get_resolutions")
        capped = min(limit, self._ledger.config.max_resolutions_per_finding)

        results = self._store.search_resolutions(
            query_text=query_text, category=category, limit=capped
        )
        self._record(
            "get_resolutions",
            {
                "category": category,
                "limit": capped,
                "query_chars": len(query_text),
            },
            len(results),
        )
        return results
