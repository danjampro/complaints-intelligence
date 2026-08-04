"""The synthetic corpus and the brief built from it.

The planted signals are the ground truth of the demo. If the generator stops
producing them, or the brief stops carrying them, every downstream test still
passes while demonstrating nothing.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import BASELINE_WEEK, REPORTING_WEEK, Settings
from complaints_intelligence.domain.brief import Direction, MetricsBrief
from complaints_intelligence.domain.complaint import Outcome, RoutingDecision
from complaints_intelligence.prompts.loader import load, load_all, prompt_hashes
from complaints_intelligence.store.duckdb_store import DuckDBStore
from complaints_intelligence.synth import signals as sig
from complaints_intelligence.synth.generator import Dataset
from complaints_intelligence.synth.taxonomy import CATEGORIES, get_node
from complaints_intelligence.synth.templates import RESOLUTION_ACTIONS


class TestPlantedVolumes:
    @pytest.mark.parametrize("signal", sig.VOLUME_SIGNALS, ids=lambda s: s.category)
    def test_counts_match_the_specification(
        self, dataset: Dataset, signal: sig.VolumeSignal
    ):
        for week, expected in (
            (BASELINE_WEEK, signal.baseline_count),
            (REPORTING_WEEK, signal.reporting_count),
        ):
            actual = sum(
                1
                for c in dataset.for_week(week)
                if c.enrichment.routing is RoutingDecision.ASSIGN
                and c.enrichment.category == signal.category
            )
            assert actual == expected, f"{signal.category} in {week}"

    def test_the_spike_is_concentrated_where_specified(self, dataset: Dataset):
        spike = [
            c
            for c in dataset.for_week(REPORTING_WEEK)
            if c.enrichment.category == sig.SPIKE.category
            and c.enrichment.routing is RoutingDecision.ASSIGN
        ]
        assert sig.SPIKE.concentrated_in is not None
        share = sum(1 for c in spike if c.channel is sig.SPIKE.concentrated_in) / len(
            spike
        )
        assert share > 0.55


class TestPlantedThemes:
    @pytest.mark.parametrize("theme", sig.THEME_SIGNALS, ids=lambda t: t.theme_id)
    def test_theme_membership_matches_the_specification(
        self, dataset: Dataset, theme: sig.ThemeSignal
    ):
        members = [
            c
            for c in dataset.for_week(REPORTING_WEEK)
            if c.enrichment.candidate_theme_id == theme.theme_id
        ]
        assert len(members) == theme.size

    def test_theme_members_are_all_abstained(self, dataset: Dataset):
        """A theme member is by definition in the residual pool."""
        for c in dataset.complaints:
            if c.enrichment.candidate_theme_id:
                assert c.enrichment.routing is RoutingDecision.ABSTAIN

    def test_the_artefact_is_measurably_duplicated(self, store: DuckDBStore):
        """The signal that gives the decoy away, measured not declared."""
        rows = {
            r["theme_id"]: r
            for r in store.query_view("v_candidate_themes", {"week": REPORTING_WEEK})
        }
        assert rows["CT-012"]["duplicate_ratio"] > 0.5
        assert rows["CT-012"]["channel_concentration"] > 0.9
        assert rows["CT-007"]["duplicate_ratio"] < 0.2
        assert rows["CT-007"]["channel_concentration"] < 0.6

    def test_coherence_alone_would_pick_the_wrong_theme(self, store: DuckDBStore):
        """Pinned because it is the most instructive property of the fixtures.

        Near-identical text is trivially coherent, so the artefact measures
        tighter than the genuine theme. Anything adjudicating on coherence
        alone would accept the decoy and reject the real signal — which is why
        the brief carries persistence, channel spread and duplication too.
        """
        artefact = store.theme_coherence("CT-012", REPORTING_WEEK)
        genuine = store.theme_coherence("CT-007", REPORTING_WEEK)
        assert artefact > genuine


class TestCorpusIntegrity:
    def test_every_category_appears(self, dataset: Dataset):
        present = {
            c.enrichment.category
            for c in dataset.complaints
            if c.enrichment.routing is RoutingDecision.ASSIGN
        }
        assert present == set(CATEGORIES)

    def test_products_match_the_taxonomy(self, dataset: Dataset):
        for c in dataset.complaints:
            if c.enrichment.routing is RoutingDecision.ASSIGN:
                assert c.product == get_node(c.enrichment.category).product

    def test_evidence_spans_resolve(self, dataset: Dataset):
        """Offsets are correct by construction; this proves the construction."""
        for c in dataset.complaints:
            for span in c.enrichment.evidence_spans:
                assert c.span_text(span).strip()

    def test_closed_complaints_have_resolution_notes(self, dataset: Dataset):
        closed = {
            c.complaint_id for c in dataset.complaints if c.status.value == "closed"
        }
        noted = {r.complaint_id for r in dataset.resolutions}
        assert noted <= closed
        assert len(noted) > len(closed) * 0.9

    def test_complaint_ids_are_unique(self, dataset: Dataset):
        ids = [c.complaint_id for c in dataset.complaints]
        assert len(ids) == len(set(ids))


class TestResolutionNoteConsistency:
    """A note must not contradict itself.

    The remediation node shows the model the outcome, the redress figure and
    the prose together, and asks it to judge whether the precedent transfers —
    partly on whether the outcome shows the action worked. A note whose
    structured fields disagree with its own text makes that judgement
    meaningless, and puts trusted store columns in conflict with untrusted
    prose with no rule available for choosing between them.
    """

    def test_every_note_agrees_with_the_action_it_came_from(self, dataset: Dataset):
        """The verdict and the money both follow the prose, not a separate draw.

        This is the regression test: before the actions were tagged, outcome
        and prose were independent and roughly a quarter of the corpus
        contradicted itself.
        """
        by_text = {
            action.text: action
            for actions in RESOLUTION_ACTIONS.values()
            for action in actions
        }
        checked = 0
        for note in dataset.resolutions:
            matched = next(
                (a for text, a in by_text.items() if note.text.endswith(text)), None
            )
            assert matched is not None, f"{note.complaint_id}: prose is not in the pool"
            assert matched.outcome is note.outcome, (
                f"{note.complaint_id}: recorded {note.outcome.value} but the prose "
                f"describes {matched.outcome.value}"
            )
            assert (note.redress_gbp > 0) is matched.pays_redress, (
                f"{note.complaint_id}: redress_gbp={note.redress_gbp} but the prose "
                f"{'describes' if matched.pays_redress else 'describes no'} payment"
            )
            checked += 1
        assert checked > 100, "too few notes to be meaningful"

    def test_every_category_can_produce_every_outcome(self):
        """Otherwise a category silently stops producing rejected precedents.

        The generator filters the pool by the outcome it drew, so a missing
        slot would leave it with nothing to choose from — and a category that
        can never yield a not-upheld note can never demonstrate a precedent
        considered and ruled out.
        """
        for category in CATEGORIES:
            available = {a.outcome for a in RESOLUTION_ACTIONS[category]}
            missing = set(Outcome) - available
            assert not missing, (
                f"{category} cannot produce {sorted(m.value for m in missing)}"
            )

    def test_a_rejected_complaint_never_describes_a_payment(self):
        """Read over the pool rather than the sampled corpus.

        A blunt instrument, in the same spirit as the choke-point source
        audits: the failure mode is a future edit that writes remediation
        prose into a not-upheld slot, and that survives every test that only
        looks at the fields.
        """
        money = ("goodwill", "compensation", "refund", "reinstated", "payment made")
        for category, actions in RESOLUTION_ACTIONS.items():
            for action in actions:
                if action.outcome is not Outcome.NOT_UPHELD:
                    continue
                assert not action.pays_redress, f"{category}: not-upheld pays redress"
                found = [word for word in money if word in action.text.lower()]
                assert not found, f"{category}: not-upheld prose mentions {found}"


class TestBrief:
    def test_carries_the_planted_signals(self, brief: MetricsBrief):
        flagged = {f.category: f for f in brief.flagged_categories}
        assert sig.SPIKE.category in flagged
        assert flagged[sig.SPIKE.category].direction is Direction.UP
        assert flagged[sig.DECLINE.category].direction is Direction.DOWN

    @pytest.mark.parametrize("signal", sig.VOLUME_SIGNALS, ids=lambda s: s.category)
    def test_significance_matches_the_specification(
        self, brief: MetricsBrief, signal: sig.VolumeSignal
    ):
        """The noise decoy must be reported as tested and not significant."""
        flagged = {f.category: f for f in brief.flagged_categories}
        assert signal.category in flagged
        assert flagged[signal.category].significant is signal.expect_significant

    def test_carries_every_candidate_theme(self, brief: MetricsBrief):
        assert {t.theme_id for t in brief.candidate_themes} == {
            t.theme_id for t in sig.THEME_SIGNALS
        }

    def test_contains_only_fact_ids_not_values(self, brief: MetricsBrief):
        """The brief is the agent's whole view, and it must be ID-only."""
        for flagged in brief.flagged_categories:
            assert flagged.count_fact_id.startswith("f_")
            assert flagged.baseline_count_fact_id.startswith("f_")
            assert flagged.change_fact_id.startswith("f_")

    def test_every_referenced_fact_resolves(
        self, brief: MetricsBrief, store: DuckDBStore
    ):
        for flagged in brief.flagged_categories:
            for fact_id in (
                flagged.count_fact_id,
                flagged.baseline_count_fact_id,
                flagged.change_fact_id,
            ):
                assert store.fact_exists(fact_id)

    def test_the_sentiment_shift_fact_is_distinct_from_the_current_value(
        self, brief: MetricsBrief
    ):
        """A shift is its own measure, not a duplicate of the current mean."""
        for signal in brief.sentiment_signals:
            assert signal.shift_fact_id != signal.current_fact_id
            assert signal.shift_fact_id != signal.baseline_fact_id

    def test_truncation_records_what_it_dropped(
        self, store: DuckDBStore, settings: Settings, brief: MetricsBrief
    ):
        """Truncation that hides its own effects is not auditable."""
        from complaints_intelligence.metrics.brief import build_brief
        from complaints_intelligence.metrics.facts import derive_facts

        tight = settings.brief.model_copy(
            update={"max_flagged_categories": 1, "max_candidate_themes": 1}
        )
        with DuckDBStore.open(settings) as fresh:
            facts, tests = derive_facts(
                fresh,
                run_id=REPORTING_WEEK,
                week=REPORTING_WEEK,
                baseline_week=BASELINE_WEEK,
                taxonomy_version=brief.taxonomy_version,
                thresholds=tight,
            )
            truncated = build_brief(
                fresh,
                facts,
                tests,
                run_id=REPORTING_WEEK,
                week=REPORTING_WEEK,
                baseline_week=BASELINE_WEEK,
                taxonomy_version=brief.taxonomy_version,
                thresholds=tight,
            )

        assert len(truncated.flagged_categories) == 1
        assert len(truncated.candidate_themes) == 1
        dropped = {s.identifier for s in truncated.skipped}
        assert "CT-012" in dropped or "CT-019" in dropped
        assert all(s.reason for s in truncated.skipped)


class TestPrompts:
    def test_every_prompt_loads_with_frontmatter(self):
        prompts = load_all("v1")
        assert set(prompts) >= {
            "plan",
            "investigate",
            "adjudicate",
            "remediate",
            "revise",
        }
        for name, prompt in prompts.items():
            assert prompt.id == name
            assert prompt.version == "v1"
            assert prompt.content_hash
            assert prompt.body

    def test_hashes_are_stable(self):
        assert prompt_hashes("v1") == prompt_hashes("v1")

    def test_a_missing_variable_raises_rather_than_rendering_a_stub(self):
        """A half-rendered prompt produces plausible output from an
        incomplete question, which does not look like a failure."""
        with pytest.raises(KeyError, match="requires variable"):
            load("investigate", "v1").render(category="payments_failed")

    def test_an_unknown_prompt_lists_what_is_available(self):
        with pytest.raises(FileNotFoundError, match="available:"):
            load("nonexistent", "v1")

    def test_prompts_forbid_writing_numbers(self):
        """The instruction has to actually be in the file."""
        for name in ("investigate", "adjudicate", "remediate"):
            body = load(name, "v1").body.lower()
            assert "never write a number" in body or "never produce a number" in body
