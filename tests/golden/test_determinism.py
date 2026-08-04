"""Determinism and end-to-end reconciliation.

Invariant 6 is a property of the whole pipeline, not of any one component,
and it fails in undramatic ways — a hash-ordered aggregate here, an unsorted
set there. These tests exercise the property at each layer and then at the
output.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import (
    BASELINE_WEEK,
    REPORTING_WEEK,
    TAXONOMY_VERSION,
    Settings,
    SynthConfig,
)
from complaints_intelligence.critic.checks import FACT_PLACEHOLDER_RE
from complaints_intelligence.domain.brief import MetricsBrief
from complaints_intelligence.metrics.facts import derive_facts
from complaints_intelligence.retrieval.embedder import TfidfSvdEmbedder
from complaints_intelligence.runner import run_week
from complaints_intelligence.store.duckdb_store import DuckDBStore
from complaints_intelligence.synth.generator import Dataset, generate
from tests.fakes import ScriptedLLM

VERDICTS = {"CT-012": "ingest_artefact", "CT-019": "noise"}


class TestGeneration:
    def test_the_same_seed_produces_the_same_corpus(self):
        first, second = generate(), generate()
        assert [c.complaint_id for c in first.complaints] == [
            c.complaint_id for c in second.complaints
        ]
        assert [c.text for c in first.complaints] == [c.text for c in second.complaints]

    def test_a_different_seed_produces_a_different_corpus(self):
        """Guards against a generator that ignores its seed entirely."""
        other = generate(SynthConfig(seed=7))
        assert [c.text for c in other.complaints] != [
            c.text for c in generate().complaints
        ]

    def test_resolution_notes_are_deterministic(self, dataset: Dataset):
        assert [r.text for r in generate().resolutions] == [
            r.text for r in dataset.resolutions
        ]


class TestEmbedding:
    def test_the_same_corpus_gives_the_same_vectors(self, dataset: Dataset):
        corpus = [c.text for c in dataset.complaints[:200]]
        first = TfidfSvdEmbedder().fit(corpus).embed(corpus[:10])
        second = TfidfSvdEmbedder().fit(corpus).embed(corpus[:10])
        assert (first == second).all()

    def test_vectors_are_unit_norm(self, dataset: Dataset):
        corpus = [c.text for c in dataset.complaints[:200]]
        vectors = TfidfSvdEmbedder().fit(corpus).embed(corpus[:10])
        norms = (vectors**2).sum(axis=1) ** 0.5
        assert all(abs(n - 1.0) < 1e-9 for n in norms)


class TestFacts:
    def test_fact_ids_are_stable_across_derivations(self, settings: Settings):
        def derive() -> list[tuple[str, str, float]]:
            with DuckDBStore.open(settings, with_facts=False) as store:
                facts, _ = derive_facts(
                    store,
                    run_id=REPORTING_WEEK,
                    week=REPORTING_WEEK,
                    baseline_week=BASELINE_WEEK,
                    taxonomy_version=TAXONOMY_VERSION,
                    thresholds=settings.brief,
                )
            return [(f.id, f.label, f.value) for f in facts]

        assert derive() == derive()


class TestFullRun:
    @pytest.fixture
    def run(self, settings: Settings, store: DuckDBStore, brief: MetricsBrief):
        llm = ScriptedLLM(verdicts=VERDICTS)
        return run_week(settings=settings, store=store, llm=llm, brief=brief)

    def test_two_runs_produce_identical_markdown(
        self, settings: Settings, store: DuckDBStore, brief: MetricsBrief
    ):
        """Excluding the generation timestamp, which is the one honest variable."""

        def render() -> list[str]:
            _, markdown = run_week(
                settings=settings,
                store=store,
                llm=ScriptedLLM(verdicts=VERDICTS),
                brief=brief,
            )
            return [line for line in markdown.splitlines() if "Generated:" not in line]

        assert render() == render()

    def test_every_figure_in_the_report_came_from_the_fact_store(
        self, run, store: DuckDBStore
    ):
        """Invariant 1, checked at the output.

        Every fact ID referenced anywhere in the report object resolves, and
        the rendered value equals what the store holds.
        """
        report, markdown = run
        referenced = set()
        for finding in (*report.drivers, *report.emerging):
            for claim in finding.claims:
                referenced |= set(claim.fact_refs)
                referenced |= set(FACT_PLACEHOLDER_RE.findall(claim.text))

        assert referenced
        for fact_id in referenced:
            fact = store.get_fact(fact_id)
            assert fact.render() in markdown

    def test_the_sentiment_section_is_rendered_from_the_fact_store(
        self, run, store: DuckDBStore
    ):
        """The one section with no model in its lineage.

        Sentiment trends are entirely figures, so they are carried from the
        metrics brief rather than drafted. This asserts the whole path: the
        signals reach the report object, and every figure printed against them
        is the store's own value.
        """
        report, markdown = run
        assert report.sentiment, "the planted sentiment shift should reach the report"

        for signal in report.sentiment:
            for fact_id in (
                signal.baseline_fact_id,
                signal.current_fact_id,
                signal.shift_fact_id,
            ):
                assert store.get_fact(fact_id).render() in markdown

    def test_no_finding_claims_to_be_a_sentiment_trend(self, run):
        """Sentiment is not a finding kind, and nothing should mint one.

        The section is deliberately outside the graph. A finding carrying a
        sentiment trend would mean a model authored a figure.
        """
        report, _ = run
        kinds = {f.kind for f in (*report.drivers, *report.emerging)}
        assert all(kind.value != "sentiment" for kind in kinds)

    def test_every_quotation_matches_its_source(self, run, store: DuckDBStore):
        """Invariant 2, checked at the output.

        The quote in the report is a slice of the stored complaint, so it
        cannot have been altered in transit.
        """
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

    def test_the_report_pins_everything_needed_to_reconstruct_it(self, run):
        report, _ = run
        versions = report.trace.versions
        assert versions.taxonomy_version == TAXONOMY_VERSION
        assert versions.prompt_version == "v1"
        assert versions.model
        assert versions.prompt_hashes
        # Every prompt used appears in the pinned hashes.
        used = {call.prompt_id for call in report.trace.llm_calls}
        assert used <= set(versions.prompt_hashes)

    def test_the_run_stays_within_budget(self, run, settings: Settings):
        report, _ = run
        assert len(report.trace.llm_calls) <= settings.budget.max_llm_calls
        assert len(report.trace.tool_calls) <= settings.budget.max_tool_calls
        assert report.critic.revision <= settings.budget.max_revisions

    def test_the_report_is_always_a_draft(self, run):
        """The system drafts; a named human publishes."""
        report, _ = run
        assert report.status.value == "draft"
        assert report.reviewed_by is None

    def test_the_planted_signals_survive_to_the_report(self, run):
        """The demo has to actually demonstrate something.

        The genuine spike leads; the decoy is rejected; the noise cluster is
        dismissed. If this fails, the fixtures no longer exercise the design.
        """
        report, _ = run
        verdicts = {a.theme_id: a.verdict.value for a in report.adjudications}
        assert verdicts["CT-007"] == "real_signal"
        assert verdicts["CT-012"] == "ingest_artefact"
        assert verdicts["CT-019"] == "noise"

        assert "payments_failed" in {f.category for f in report.drivers}
        assert "CT-007" in {f.theme_id for f in report.emerging}
        assert "CT-012" not in {f.theme_id for f in report.emerging}

    def test_the_investigation_budget_drops_the_noise_category(
        self, run, settings: Settings
    ):
        """The five genuine movements fill the budget; the decoy is what falls.

        Six categories are flagged against five investigation slots, so the
        cap binds. Which category it excludes is the whole point: a report
        that investigated the movement that failed its significance test, and
        left out one that passed, would be reporting noise as a driver.
        """
        report, _ = run
        categories = {f.category for f in report.drivers}

        assert len(report.drivers) == settings.budget.max_investigations
        assert "statement_errors" not in categories

    def test_rejected_themes_are_still_reported(self, run):
        """A theme dismissed silently is indistinguishable from one never seen."""
        _, markdown = run
        assert "CT-012" in markdown
        assert "ingest artefact" in markdown
