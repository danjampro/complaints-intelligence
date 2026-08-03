"""Repository protocols.

The agent and the metrics layer depend on these, never on DuckDB or BigQuery.
Two implementations exist: ``DuckDBStore`` (used everywhere here) and
``BigQueryStore`` (documented, unexecuted, the production path).

Every method is a *parameterised* query. There is deliberately no
``execute_sql``: the agent reaches the store only through this surface, so
free-form SQL is not reachable from a model — it is absent from the type, not
merely discouraged.

Method names are distinct across the three protocols so a single object can
satisfy all of them, which is what ``DuckDBStore`` does. Callers still depend
on the narrow protocol they need.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from complaints_intelligence.domain.complaint import ComplaintEnvelope, ResolutionNote
from complaints_intelligence.domain.fact import Fact


@runtime_checkable
class ComplaintRepository(Protocol):
    """Read access to the complaint store."""

    def get_complaint(self, complaint_id: str) -> ComplaintEnvelope:
        """Fetch one complaint. Raises ``KeyError`` if absent."""
        ...

    def get_complaints(
        self, complaint_ids: Sequence[str]
    ) -> tuple[ComplaintEnvelope, ...]:
        """Fetch several complaints, preserving the order requested."""
        ...

    def exemplars(
        self,
        *,
        query_text: str,
        week: str,
        category: str | None = None,
        theme_id: str | None = None,
        channel: str | None = None,
        limit: int = 6,
    ) -> tuple[ComplaintEnvelope, ...]:
        """Retrieve representative complaints by vector similarity.

        Metadata filters are applied before ranking, so a request scoped to a
        week and category cannot return anything outside it.
        """
        ...

    def category_counts(self, week: str) -> dict[str, int]:
        """Assigned complaint counts by category for a week."""
        ...

    def theme_members(self, theme_id: str, week: str) -> tuple[ComplaintEnvelope, ...]:
        """Every residual-pool member of a candidate theme in a week."""
        ...


@runtime_checkable
class ResolutionRepository(Protocol):
    """Read access to resolution notes on closed complaints.

    The sole knowledge source for remediation recommendations.
    """

    def search_resolutions(
        self,
        *,
        query_text: str,
        category: str | None = None,
        limit: int = 6,
    ) -> tuple[ResolutionNote, ...]:
        """Retrieve resolution notes for comparable closed complaints."""
        ...

    def get_resolution(self, complaint_id: str) -> ResolutionNote | None:
        """Fetch the note for one complaint, if it is closed."""
        ...


@runtime_checkable
class FactStore(Protocol):
    """Read access to the immutable, run-stamped facts for a week."""

    def get_fact(self, fact_id: str) -> Fact:
        """Resolve a fact ID. Raises ``ProvenanceError`` if it does not exist.

        The agent may reference any fact ID it likes; this is where an
        invented one is caught, before a figure reaches a reader.
        """
        ...

    def all_facts(self) -> tuple[Fact, ...]:
        """Every fact in the run."""
        ...

    def fact_exists(self, fact_id: str) -> bool:
        """Whether a fact ID resolves, without raising."""
        ...
