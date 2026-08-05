"""Proof that each verification check fires when provoked.

A check that exists is not a check that works. Every defect below is injected
through the *full graph*, so what is tested is the path a real failure would
take — including whether the revise loop can repair it, and whether it stops.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import Settings
from complaints_intelligence.critic import published_prose
from complaints_intelligence.inputs import MetricsBrief
from complaints_intelligence.outputs import FACT_PLACEHOLDER_RE, Report
from complaints_intelligence.runner import run_week
from complaints_intelligence.store import Store
from tests.fakes import ScriptedLLM, StubbornLLM


def _run(store: Store, brief: MetricsBrief, llm: ScriptedLLM) -> tuple[Report, str]:
    return run_week(settings=Settings(), store=store, llm=llm, brief=brief)


def _failed(report: Report) -> set[str]:
    return {check.name for check in report.critic.failures}


@pytest.mark.parametrize(
    ("defect", "expected_check"),
    [
        ("literal_number", "no_literal_numbers"),
        ("bad_fact", "facts_resolve"),
        ("one_citation", "citations_present"),
        ("bad_offsets", "citations_resolve"),
        ("pii", "no_pii"),
    ],
)
def test_each_check_fires_on_its_own_defect(
    store: Store, brief: MetricsBrief, defect: str, expected_check: str
):
    """The whole assurance argument in one test: provoke each failure mode
    through the graph and confirm the right check catches it."""
    report, _ = _run(
        store,
        brief,
        StubbornLLM(defects=frozenset({defect}), verdicts={"CT-012": "noise"}),
    )
    assert expected_check in _failed(report)
    assert not report.critic.passed


def test_a_rejected_themes_rationale_is_verified_too(store: Store, brief: MetricsBrief):
    """A rejected theme never becomes a finding, but its rationale is still
    published in section 3 — so checking findings alone would leave that prose
    unverified."""
    report, _ = _run(store, brief, ScriptedLLM(verdicts={"CT-012": "ingest_artefact"}))
    rejected = [a for a in report.adjudications if a.theme_id == "CT-012"]
    assert rejected, "the decoy should have been adjudicated"

    locations = {location for location, _, _ in published_prose((), rejected)}
    assert "CT-012" in locations


def test_a_clean_draft_passes_every_check(store: Store, brief: MetricsBrief):
    report, _ = _run(store, brief, ScriptedLLM(verdicts={"CT-012": "ingest_artefact"}))
    assert report.critic.passed, _failed(report)
    assert len(report.critic.checks) == 5


def test_the_revise_loop_repairs_a_recoverable_defect(
    store: Store, brief: MetricsBrief
):
    """``ScriptedLLM`` returns a clean draft on revision, so the loop should
    close and the report should pass."""
    report, _ = _run(
        store,
        brief,
        ScriptedLLM(
            defects=frozenset({"literal_number"}),
            verdicts={"CT-012": "ingest_artefact"},
        ),
    )
    assert report.critic.passed, _failed(report)
    assert report.critic.revision >= 1


def test_the_revise_loop_terminates_when_repair_is_impossible(
    store: Store, brief: MetricsBrief, settings: Settings
):
    """The budget is what makes the loop a loop rather than a hang."""
    report, _ = _run(store, brief, StubbornLLM(defects=frozenset({"literal_number"})))
    assert not report.critic.passed
    assert report.critic.revision == settings.budget.max_revisions


def test_an_adjudication_finding_cannot_be_revised_and_says_so(
    store: Store, brief: MetricsBrief
):
    """Emerging-theme findings come from adjudication, with their own evidence
    and output shape. Redrafting one through the investigate schema would
    restate a verdict as a driver finding, so the run records that instead."""
    report, _ = _run(store, brief, StubbornLLM(defects=frozenset({"bad_offsets"})))
    assert any("cannot be revised" in note for note in report.trace.notes)


def test_a_fabricated_figure_never_reaches_the_reader(
    store: Store, brief: MetricsBrief
):
    """A fact ID the store does not hold fails verification, and the report is
    marked unpublishable rather than printing an invented number."""
    report, markdown = _run(store, brief, StubbornLLM(defects=frozenset({"bad_fact"})))
    assert "facts_resolve" in _failed(report)
    assert "did not pass verification" in markdown


def test_a_failing_draft_is_still_rendered_so_a_reviewer_can_see_why(
    store: Store, brief: MetricsBrief
):
    report, markdown = _run(
        store, brief, StubbornLLM(defects=frozenset({"literal_number"}))
    )
    assert report.status.value == "draft"
    assert "**FAIL**" in markdown


def test_a_clean_run_leaves_no_unresolved_placeholder(
    store: Store, brief: MetricsBrief
):
    _, markdown = _run(
        store, brief, ScriptedLLM(verdicts={"CT-012": "ingest_artefact"})
    )
    assert not FACT_PLACEHOLDER_RE.search(markdown)
