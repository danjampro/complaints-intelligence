"""End-to-end behaviour of one weekly run.

These assert the invariants at the output, where they actually matter: every
figure came from the fact store, every quotation is a slice of its source, and
the planted signals reach the report the way the design says they should.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import Settings
from complaints_intelligence.inputs import MetricsBrief
from complaints_intelligence.outputs import FACT_PLACEHOLDER_RE, Report
from complaints_intelligence.render import snap_span
from complaints_intelligence.runner import run_week
from complaints_intelligence.store import Store
from tests.fakes import ScriptedLLM

VERDICTS = {"CT-012": "ingest_artefact"}


@pytest.fixture(scope="module")
def run(brief: MetricsBrief, store: Store) -> tuple[Report, str]:
    return run_week(
        settings=Settings(),
        store=store,
        llm=ScriptedLLM(verdicts=VERDICTS),
        brief=brief,
    )


class TestTheBrief:
    def test_significant_movements_rank_above_the_one_that_failed_its_test(
        self, brief: MetricsBrief
    ):
        """The order decides what the investigation budget can reach, so a
        movement that failed correction must not displace one that held up."""
        categories = [f.category for f in brief.flagged_categories]
        assert categories[-1] == "statement_errors"
        assert all(f.significant for f in brief.flagged_categories[:-1])

    def test_the_brief_carries_fact_ids_and_never_values(self, brief: MetricsBrief):
        for flagged in brief.flagged_categories:
            assert flagged.count_fact_id.startswith("f_")
            assert flagged.baseline_count_fact_id.startswith("f_")

    def test_every_fact_the_brief_references_resolves(
        self, brief: MetricsBrief, store: Store
    ):
        for flagged in brief.flagged_categories:
            assert store.get_fact(flagged.count_fact_id)
        for signal in brief.sentiment_signals:
            assert store.get_fact(signal.shift_fact_id)
        for theme in brief.candidate_themes:
            assert store.get_fact(theme.size_fact_id)

    def test_cluster_coherence_points_the_wrong_way(self, brief: MetricsBrief):
        """The single most instructive result in the fixture.

        The duplicated CRM notes are far tighter than the genuine emerging
        theme, because near-identical text is trivially coherent. Anything
        adjudicating on coherence alone would accept the decoy and reject the
        real signal — which is why the brief carries three other signals.
        """
        themes = {t.theme_id: t for t in brief.candidate_themes}
        assert themes["CT-012"].coherence > themes["CT-007"].coherence

        assert themes["CT-012"].duplicate_ratio > 0.5
        assert themes["CT-012"].channel_concentration == 1.0
        assert themes["CT-007"].duplicate_ratio < 0.2
        assert themes["CT-007"].channel_concentration < 0.6


class TestGrounding:
    def test_every_figure_in_the_report_came_from_the_fact_store(
        self, run: tuple[Report, str], store: Store
    ):
        """Invariant 1, checked at the output: every figure printed in the
        report is a placeholder the store resolved."""
        report, markdown = run
        printed = {
            fact_id
            for finding in (*report.drivers, *report.emerging)
            for claim in finding.claims
            for fact_id in FACT_PLACEHOLDER_RE.findall(claim.text)
        }
        assert printed
        for fact_id in printed:
            assert store.get_fact(fact_id).render() in markdown

    def test_every_declared_fact_reference_resolves(
        self, run: tuple[Report, str], store: Store
    ):
        report, _ = run
        for finding in (*report.drivers, *report.emerging):
            for claim in finding.claims:
                for fact_id in claim.fact_refs:
                    assert store.fact_exists(fact_id)

    def test_no_unresolved_placeholder_survives_into_the_report(
        self, run: tuple[Report, str]
    ):
        _, markdown = run
        assert not FACT_PLACEHOLDER_RE.search(markdown)

    def test_every_quotation_is_a_slice_of_its_source(
        self, run: tuple[Report, str], store: Store
    ):
        """Invariant 2. The model never handles the words it quotes."""
        report, _ = run
        checked = 0
        for finding in (*report.drivers, *report.emerging):
            for claim in finding.claims:
                for citation in claim.citations:
                    complaint = store.get_complaint(citation.complaint_id)
                    assert citation.end <= len(complaint.text)
                    assert complaint.text[citation.start : citation.end]
                    checked += 1
        assert checked > 0

    def test_every_rendered_quotation_begins_and_ends_on_a_word_boundary(
        self, run: tuple[Report, str], store: Store
    ):
        """Model offsets land mid-word often enough to make the report read as
        broken. Snapping only ever widens, so the quote stays a slice of stored
        text and the misquotation guarantee is untouched."""
        report, _ = run
        checked = 0
        for finding in (*report.drivers, *report.emerging):
            for claim in finding.claims:
                for citation in claim.citations:
                    text = store.get_complaint(citation.complaint_id).text
                    start, end = snap_span(text, citation.start, citation.end)
                    assert start <= citation.start and end >= citation.end
                    assert start == 0 or not text[start - 1].isalnum()
                    assert end == len(text) or not text[end].isalnum()
                    checked += 1
        assert checked > 0

    def test_the_sentiment_section_is_rendered_entirely_from_the_fact_store(
        self, run: tuple[Report, str], store: Store
    ):
        """The one section with no model anywhere in its lineage."""
        report, markdown = run
        assert report.sentiment
        for signal in report.sentiment:
            for fact_id in (
                signal.baseline_fact_id,
                signal.current_fact_id,
                signal.shift_fact_id,
            ):
                assert store.get_fact(fact_id).render() in markdown

    def test_the_report_is_deterministic(self, brief: MetricsBrief, store: Store):
        """Excluding the generation timestamp, the one honest variable."""

        def render() -> list[str]:
            _, markdown = run_week(
                settings=Settings(),
                store=store,
                llm=ScriptedLLM(verdicts=VERDICTS),
                brief=brief,
            )
            return [line for line in markdown.splitlines() if "Generated:" not in line]

        assert render() == render()


class TestRequiredOutputs:
    def test_the_report_leads_with_the_top_drivers(
        self, run: tuple[Report, str], settings: Settings
    ):
        report, _ = run
        assert len(report.drivers) == settings.budget.max_investigations
        assert "payments_failed" in {f.category for f in report.drivers}

    def test_the_investigation_budget_drops_the_movement_that_was_not_significant(
        self, run: tuple[Report, str]
    ):
        """Six categories are flagged against five slots, so the cap binds.
        Which one it excludes is the point."""
        report, _ = run
        assert "statement_errors" not in {f.category for f in report.drivers}

    def test_the_genuine_theme_is_accepted_and_the_decoy_is_rejected(
        self, run: tuple[Report, str]
    ):
        report, _ = run
        verdicts = {a.theme_id: a.verdict.value for a in report.adjudications}
        assert verdicts["CT-007"] == "real_signal"
        assert verdicts["CT-012"] == "ingest_artefact"
        assert "CT-007" in {f.theme_id for f in report.emerging}
        assert "CT-012" not in {f.theme_id for f in report.emerging}

    def test_a_rejected_theme_is_still_reported(self, run: tuple[Report, str]):
        """A theme dismissed silently is indistinguishable from one never
        examined."""
        _, markdown = run
        assert "CT-012" in markdown
        assert "ingest artefact" in markdown

    def test_remediations_are_grounded_in_named_precedent(
        self, run: tuple[Report, str], store: Store
    ):
        report, _ = run
        assert report.remediations
        for remediation in report.remediations:
            assert remediation.precedents
            for precedent in remediation.precedents:
                assert store.get_resolution(precedent.complaint_id) is not None


class TestRunDiscipline:
    def test_the_run_stays_within_budget(
        self, run: tuple[Report, str], settings: Settings
    ):
        report, _ = run
        assert report.trace.llm_calls <= settings.budget.max_llm_calls
        assert report.trace.tool_calls <= settings.budget.max_tool_calls
        assert report.critic.revision <= settings.budget.max_revisions

    def test_the_report_is_always_a_draft(self, run: tuple[Report, str]):
        """The system drafts; a named human publishes."""
        report, _ = run
        assert report.status.value == "draft"
        assert report.reviewed_by is None

    def test_the_trace_pins_what_is_needed_to_reconstruct_the_report(
        self, run: tuple[Report, str]
    ):
        report, _ = run
        assert report.trace.model
        assert report.trace.prompt_version == "v1"
        assert report.trace.taxonomy_version
        assert report.trace.node_sequence[0] == "investigate"
        assert "critic" in report.trace.node_sequence
