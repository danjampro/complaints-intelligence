"""The store: retrieval scoping, the tool contract, and determinism."""

from __future__ import annotations

import pytest

from complaints_intelligence.agent.budgets import BudgetLedger
from complaints_intelligence.agent.tools import ToolBelt
from complaints_intelligence.config import BASELINE_WEEK, REPORTING_WEEK, Settings
from complaints_intelligence.errors import ProvenanceError, ToolContractError
from complaints_intelligence.store.duckdb_store import DuckDBStore
from complaints_intelligence.store.protocols import (
    ComplaintRepository,
    FactStore,
    ResolutionRepository,
)


class TestProtocolConformance:
    def test_store_satisfies_all_three_protocols(self, store: DuckDBStore):
        """One object, three narrow protocols. Callers depend on the protocol."""
        assert isinstance(store, ComplaintRepository)
        assert isinstance(store, ResolutionRepository)
        assert isinstance(store, FactStore)


class TestRetrievalScoping:
    def test_category_filter_is_applied_before_ranking(self, store: DuckDBStore):
        """Containment, not optimisation.

        An exemplar from the wrong category would silently misrepresent the
        finding it is cited to support.
        """
        results = store.exemplars(
            query_text="round up savings taking money twice",
            week=REPORTING_WEEK,
            category="branch_closure",
            limit=5,
        )
        assert results
        assert all(c.enrichment.category == "branch_closure" for c in results)

    def test_week_filter_is_applied(self, store: DuckDBStore):
        results = store.exemplars(
            query_text="payment failed", week=BASELINE_WEEK, limit=5
        )
        assert results
        assert all(c.week == BASELINE_WEEK for c in results)

    def test_theme_filter_returns_only_members(self, store: DuckDBStore):
        results = store.exemplars(
            query_text="round up savings",
            week=REPORTING_WEEK,
            theme_id="CT-007",
            limit=5,
        )
        assert results
        assert all(c.enrichment.candidate_theme_id == "CT-007" for c in results)

    def test_retrieval_is_relevant(self, store: DuckDBStore):
        """The RAG substrate has to actually work, not merely return rows."""
        results = store.exemplars(
            query_text="round up savings pot took the money twice",
            week=REPORTING_WEEK,
            theme_id="CT-007",
            limit=3,
        )
        assert any("round" in c.text.lower() for c in results)

    def test_results_are_deterministic(self, store: DuckDBStore):
        first = store.exemplars(
            query_text="payment failed", week=REPORTING_WEEK, limit=5
        )
        second = store.exemplars(
            query_text="payment failed", week=REPORTING_WEEK, limit=5
        )
        assert [c.complaint_id for c in first] == [c.complaint_id for c in second]

    def test_view_rows_are_ordered_deterministically(self, store: DuckDBStore):
        """Aggregates come back in hash order without an explicit sort.

        That would make derived facts — and therefore the report — differ
        between runs on identical input.
        """
        first = store.query_view("v_health_indicators")
        second = store.query_view("v_health_indicators")
        assert [r["week"] for r in first] == [r["week"] for r in second]


class TestFactStore:
    def test_known_fact_resolves(self, store: DuckDBStore):
        facts = store.all_facts()
        assert facts
        assert store.get_fact(facts[0].id).id == facts[0].id

    def test_unknown_fact_raises(self, store: DuckDBStore):
        """Invariant 1 is an assertion. An invented ID must not resolve."""
        with pytest.raises(ProvenanceError, match="does not resolve"):
            store.get_fact("f_9999")

    def test_exists_does_not_raise(self, store: DuckDBStore):
        assert not store.fact_exists("f_9999")

    def test_facts_reconcile_with_the_store(self, store: DuckDBStore):
        """Every fact's provenance re-derives its value.

        This is the traceability claim, tested rather than asserted: running
        the recorded view and parameters must return the recorded number.
        """
        checked = 0
        for fact in store.all_facts():
            if fact.provenance.view != "v_weekly_category_counts":
                continue
            if "measure" in fact.provenance.params:
                continue
            rows = store.query_view(fact.provenance.view, dict(fact.provenance.params))
            assert rows, f"{fact.id} provenance returned nothing"
            assert float(rows[0]["complaint_count"]) == fact.value
            checked += 1
        assert checked > 10


class TestToolContract:
    @pytest.fixture
    def tools(self, store: DuckDBStore, settings: Settings) -> ToolBelt:
        belt = ToolBelt(store, BudgetLedger(config=settings.budget))
        belt.entering("test")
        return belt

    def test_allowlisted_view_is_readable(self, tools: ToolBelt):
        assert tools.query_metrics("v_health_indicators")

    def test_unlisted_view_is_rejected(self, tools: ToolBelt):
        with pytest.raises(ToolContractError, match="not available"):
            tools.query_metrics("complaints")

    def test_sql_injection_through_the_view_name_is_rejected(self, tools: ToolBelt):
        with pytest.raises(ToolContractError):
            tools.query_metrics("v_health_indicators; DROP TABLE complaints")

    def test_unlisted_filter_column_is_rejected(self, tools: ToolBelt):
        with pytest.raises(ToolContractError, match="not permitted"):
            tools.query_metrics("v_health_indicators", {"1=1 OR week": "x"})

    def test_measure_columns_are_not_filterable(self, tools: ToolBelt):
        """Filtering on a value is computing a statistic one query at a time."""
        with pytest.raises(ToolContractError):
            tools.query_metrics("v_health_indicators", {"abstention_rate": "0.16"})

    def test_there_is_no_raw_sql_tool(self, tools: ToolBelt):
        """Absent from the type, not merely discouraged."""
        surface = {a for a in dir(tools) if not a.startswith("_")}
        assert surface == {
            "query_metrics",
            "get_exemplars",
            "get_resolutions",
            "entering",
            "calls",
        }

    def test_every_call_is_traced(self, tools: ToolBelt):
        tools.query_metrics("v_health_indicators")
        tools.get_exemplars(query_text="payment", week=REPORTING_WEEK, limit=2)
        assert [c.tool for c in tools.calls] == ["query_metrics", "get_exemplars"]
        assert all(c.node == "test" for c in tools.calls)

    def test_limit_is_capped_by_budget(self, tools: ToolBelt, settings: Settings):
        results = tools.get_exemplars(
            query_text="payment", week=REPORTING_WEEK, limit=10_000
        )
        assert len(results) <= settings.budget.max_exemplars_per_finding
