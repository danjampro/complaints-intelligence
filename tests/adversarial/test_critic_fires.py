"""Each critic check, provoked through the real graph.

The unit tests prove the checks work in isolation. These prove they are
actually wired in: a defective draft goes through the whole pipeline —
retrieval, prompting, mapping to domain objects, verification — and the run
refuses to produce a clean report.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import Settings
from complaints_intelligence.domain.brief import MetricsBrief
from complaints_intelligence.runner import run_week
from complaints_intelligence.store.duckdb_store import DuckDBStore
from tests.fakes import ScriptedLLM

VERDICTS = {"CT-012": "ingest_artefact", "CT-019": "noise"}


class StubbornLLM(ScriptedLLM):
    """A model whose revisions reproduce the same defect.

    Needed to observe a check failing at the end of a run: the ordinary
    scripted reviser repairs the draft, so the final report passes and the
    failure is only visible mid-graph. This isolates "the check fires and the
    run refuses" from "the revise loop works", which are separate claims.
    """

    def _revise(self, rendered: str):
        return self._investigate(rendered)


def _run(
    settings: Settings,
    store: DuckDBStore,
    brief: MetricsBrief,
    defects: set[str],
    *,
    stubborn: bool = False,
):
    factory = StubbornLLM if stubborn else ScriptedLLM
    llm = factory(defects=frozenset(defects), verdicts=VERDICTS)
    return run_week(settings=settings, store=store, llm=llm, brief=brief)


@pytest.mark.parametrize(
    ("defect", "expected_check"),
    [
        ("bad_fact", "facts_resolve"),
        ("literal_number", "no_literal_numbers"),
        ("fact_placement", "fact_placement"),
        ("one_citation", "citations_present"),
        ("bad_offsets", "citations_resolve"),
        ("causal", "no_causal_language"),
        ("pii", "no_pii"),
    ],
)
def test_an_unrepaired_defect_fails_the_expected_check(
    settings: Settings,
    store: DuckDBStore,
    brief: MetricsBrief,
    defect: str,
    expected_check: str,
):
    """A defect the model will not fix must fail the run, every time."""
    report, _ = _run(settings, store, brief, {defect}, stubborn=True)
    assert not report.critic.passed
    assert expected_check in {c.name for c in report.critic.failures}


@pytest.mark.parametrize(
    "defect",
    ["bad_fact", "literal_number", "fact_placement", "one_citation", "causal", "pii"],
)
def test_the_revise_loop_repairs_a_defect_in_a_driver_finding(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief, defect: str
):
    """The other half: a reviser that does fix things produces a clean report."""
    report, _ = _run(settings, store, brief, {defect})
    assert "revise" in report.trace.node_sequence
    assert report.critic.passed, [(c.name, c.offending) for c in report.critic.failures]


def test_a_defect_in_an_adjudication_finding_cannot_be_revised(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    """A known limitation, pinned so it is a decision rather than a surprise.

    ``revise`` re-prompts through the investigate schema, which does not fit
    an adjudication — re-drafting one that way would restate a verdict as a
    driver finding. So a defect originating in ``adjudicate`` fails the run
    instead of being repaired, and the run says so.
    """
    report, _ = _run(settings, store, brief, {"bad_offsets"})
    assert not report.critic.passed
    assert any(
        o.startswith("E-") for check in report.critic.failures for o in check.offending
    )
    assert any("cannot be revised" in note for note in report.trace.notes)


def test_a_clean_draft_passes_every_check(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    report, _ = _run(settings, store, brief, set())
    assert report.critic.passed, [(c.name, c.offending) for c in report.critic.failures]


def test_a_failing_draft_is_still_marked_draft_and_says_so(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    """A report that fails verification must announce it, not hide it."""
    report, markdown = _run(settings, store, brief, {"bad_fact"}, stubborn=True)
    assert report.status.value == "draft"
    assert "did not pass verification" in markdown
    assert "must not be published" in markdown


def test_the_revise_loop_is_bounded_and_terminates(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    """A reviser that never repairs anything must not loop forever."""
    report, _ = _run(settings, store, brief, {"literal_number"}, stubborn=True)

    assert not report.critic.passed
    assert report.critic.revision == settings.budget.max_revisions
    assert any("revision budget exhausted" in n for n in report.trace.notes)
    assert report.trace.node_sequence.count("revise") == (settings.budget.max_revisions)


def test_a_fabricated_figure_never_reaches_the_reader(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    """Invariant 1, tested at the output.

    The model emits `f_9999`, which does not exist. It must never appear as a
    number: the placeholder either survives unresolved in a report marked as
    failed, or the run stops. What must not happen is a plausible figure.
    """
    report, markdown = _run(settings, store, brief, {"bad_fact"}, stubborn=True)
    assert not report.critic.passed
    assert "f_9999" in markdown
    # Unresolved, not substituted with anything a reader could mistake for
    # a real figure.
    assert "{{f_9999}}" in markdown


def test_a_clean_run_produces_no_unresolved_placeholders(
    settings: Settings, store: DuckDBStore, brief: MetricsBrief
):
    """The complement: when verification passes, every figure resolved."""
    report, markdown = _run(settings, store, brief, set())
    assert report.critic.passed
    assert "{{f_" not in markdown
