"""Each critic check in isolation.

A check that exists but never fires is not a control. These tests provoke each
one directly; the adversarial suite then provokes them through the real graph.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.config import CriticThresholds
from complaints_intelligence.critic import checks
from complaints_intelligence.domain.finding import (
    Citation,
    Claim,
    Finding,
    FindingKind,
)
from complaints_intelligence.store.duckdb_store import DuckDBStore

THRESHOLDS = CriticThresholds()


def make_finding(
    text: str,
    *,
    fact_refs: tuple[str, ...] = (),
    citations: tuple[Citation, ...] = (),
    requires_confirmation: bool = False,
    headline: str = "A plain headline about customer complaints.",
) -> Finding:
    return Finding(
        finding_id="F-01",
        kind=FindingKind.DRIVER,
        headline=headline,
        claims=(
            Claim(
                text=text,
                fact_refs=fact_refs,
                citations=citations,
                requires_confirmation=requires_confirmation,
            ),
        ),
        category="payments_failed",
    )


class TestFactsResolve:
    def test_passes_when_facts_exist(self, store: DuckDBStore):
        real = store.all_facts()[0].id
        finding = make_finding(f"Volumes moved to {{{{{real}}}}}.", fact_refs=(real,))
        assert checks.check_facts_resolve([finding], store).passed

    def test_fails_on_an_invented_fact_id(self, store: DuckDBStore):
        finding = make_finding("Volumes moved to {{f_9999}}.", fact_refs=("f_9999",))
        result = checks.check_facts_resolve([finding], store)
        assert not result.passed
        assert "f_9999" in result.offending[0]

    def test_catches_an_id_embedded_in_text_but_not_declared(self, store: DuckDBStore):
        """The render stage substitutes from the text, not from ``fact_refs``."""
        finding = make_finding("Volumes moved to {{f_9999}}.", fact_refs=())
        assert not checks.check_facts_resolve([finding], store).passed


class TestNoLiteralNumbers:
    def test_passes_with_only_placeholders(self):
        finding = make_finding("Customers report failed transfers {{f_0001}}.")
        assert checks.check_no_literal_numbers([finding]).passed

    def test_fails_on_a_digit(self):
        finding = make_finding("Volumes reached 142 complaints.")
        assert not checks.check_no_literal_numbers([finding]).passed

    def test_fails_on_a_written_number(self):
        """A model told not to type digits will spell them instead."""
        finding = make_finding("Volumes reached one hundred and forty-two cases.")
        assert not checks.check_no_literal_numbers([finding]).passed

    @pytest.mark.parametrize("word", ["half", "dozen", "quarter", "hundred", "ninety"])
    def test_fails_on_scale_words(self, word: str):
        assert not checks.check_no_literal_numbers(
            [make_finding(f"Charges were a {word} of what customers expected.")]
        ).passed

    @pytest.mark.parametrize("word", ["two", "twelve", "fifteen"])
    def test_a_small_cardinal_counting_a_plural_noun_fails(self, word: str):
        assert not checks.check_no_literal_numbers(
            [make_finding(f"We received {word} complaints about the charge.")]
        ).passed

    @pytest.mark.parametrize(
        "sentence",
        [
            "One customer described being charged twice for a single purchase.",
            "Another customer said the transfer never arrived.",
            "In one case the payment was reversed without notice.",
        ],
    )
    def test_a_small_cardinal_used_as_a_determiner_is_allowed(self, sentence: str):
        """Ordinary English, not a figure.

        Flagging these costs a revision round and pushes the prose towards a
        stilted register, which is the opposite of what the report is for.
        """
        assert checks.check_no_literal_numbers([make_finding(sentence)]).passed

    def test_a_written_out_large_number_is_still_caught(self):
        """The failure mode the rule exists for, after the tiering."""
        assert not checks.check_no_literal_numbers(
            [make_finding("Volumes reached one hundred and forty-two this week.")]
        ).passed

    @pytest.mark.parametrize("word", ["double", "triple"])
    def test_descriptive_multiplier_words_are_allowed(self, word: str):
        """ "A double debit" names the fault; it is not a quantity.

        Flagging these forced the report to describe the problem in worse
        English than the customers used.
        """
        assert checks.check_no_literal_numbers(
            [make_finding(f"Customers describe a {word} debit on each purchase.")]
        ).passed

    def test_a_theme_identifier_is_not_a_figure(self):
        """``CT-007`` is a reference, not a number.

        Without this, a finding about a theme fails on the digits in its own
        subject.
        """
        assert checks.check_no_literal_numbers(
            [make_finding("Theme CT-007 concerns duplicated savings transfers.")]
        ).passed

    def test_a_complaint_identifier_is_not_a_figure(self):
        assert checks.check_no_literal_numbers(
            [make_finding("As set out in CMP-2026W31-0541, transfers repeated.")]
        ).passed


class TestCitations:
    def test_two_citations_pass(self, store: DuckDBStore):
        ids = [
            c.complaint_id
            for c in store.exemplars(query_text="payment", week="2026-W31", limit=2)
        ]
        citations = tuple(Citation(complaint_id=i, start=0, end=15) for i in ids)
        finding = make_finding("Customers describe failures.", citations=citations)
        assert checks.check_citations_present([finding], THRESHOLDS).passed
        assert checks.check_citations_resolve([finding], store).passed

    def test_one_citation_fails(self, store: DuckDBStore):
        """Two, not one. A single complaint is an anecdote."""
        first = store.exemplars(query_text="payment", week="2026-W31", limit=1)[0]
        finding = make_finding(
            "Customers describe failures.",
            citations=(Citation(complaint_id=first.complaint_id, start=0, end=15),),
        )
        assert not checks.check_citations_present([finding], THRESHOLDS).passed

    def test_a_claim_that_is_only_a_fact_needs_no_citation(self):
        """The fact store already supports it; a complaint would add nothing."""
        finding = make_finding("{{f_0001}}")
        assert checks.check_citations_present([finding], THRESHOLDS).passed

    def test_a_hypothesis_needs_no_citation(self):
        """A hypothesis is a step beyond what the evidence shows.

        Requiring evidence for it makes the mechanism unusable, and an
        unusable hypothesis field pushes causal speculation back into the
        claims — the outcome the design exists to prevent.
        """
        finding = make_finding(
            "The rise may follow a change to the payments gateway.",
            requires_confirmation=True,
        )
        assert checks.check_citations_present([finding], THRESHOLDS).passed
        assert checks.check_no_causal_language([finding]).passed

    def test_offsets_beyond_the_text_fail(self, store: DuckDBStore):
        first = store.exemplars(query_text="payment", week="2026-W31", limit=1)[0]
        finding = make_finding(
            "Customers describe failures.",
            citations=(
                Citation(complaint_id=first.complaint_id, start=99_000, end=99_100),
            ),
        )
        assert not checks.check_citations_resolve([finding], store).passed

    def test_an_unknown_complaint_fails(self, store: DuckDBStore):
        finding = make_finding(
            "Customers describe failures.",
            citations=(Citation(complaint_id="CMP-NOPE-0001", start=0, end=5),),
        )
        result = checks.check_citations_resolve([finding], store)
        assert not result.passed
        assert "CMP-NOPE-0001" in result.offending[0]


class TestCausalLanguage:
    @pytest.mark.parametrize(
        "phrase",
        ["caused by", "because of", "due to", "led to", "resulted in", "driven by"],
    )
    def test_causal_phrases_fail(self, phrase: str):
        finding = make_finding(f"Failures were {phrase} a system fault.")
        assert not checks.check_no_causal_language([finding]).passed

    @pytest.mark.parametrize("phrase", ["coincident with", "alongside", "following"])
    def test_correlational_phrases_pass(self, phrase: str):
        finding = make_finding(f"Failures were {phrase} a release.")
        assert checks.check_no_causal_language([finding]).passed

    def test_a_flagged_hypothesis_may_be_causal(self):
        """The sanctioned route for a causal belief.

        Suppressing it entirely would push it back into the claims as causal
        language on the next draft.
        """
        finding = make_finding(
            "Failures may be caused by the release.", requires_confirmation=True
        )
        assert checks.check_no_causal_language([finding]).passed


class TestPii:
    @pytest.mark.parametrize(
        "text",
        [
            "Contact margaret.threlfall@example.com for detail.",
            "Reach the customer on 07700 900412.",
            "The sort code is 40-12-88.",
            "Date of birth 14/03/1958.",
            "Account 61554920 was affected.",
        ],
    )
    def test_identifiers_are_caught(self, text: str):
        assert not checks.check_no_pii([("F-01", text)]).passed

    def test_clean_text_passes(self):
        assert checks.check_no_pii(
            [("F-01", "Customers report transfers that do not complete.")]
        ).passed


class TestAcronyms:
    def test_known_acronyms_pass(self):
        finding = make_finding("The FCA and FOS were both notified.")
        assert checks.check_no_unexplained_acronyms([finding]).passed

    def test_unknown_acronyms_fail(self):
        finding = make_finding("The PXQ team reviewed the case.")
        assert not checks.check_no_unexplained_acronyms([finding]).passed

    def test_an_expansion_on_first_use_passes(self):
        finding = make_finding("The Payment Exception Queue (PXQ) was reviewed.")
        assert checks.check_no_unexplained_acronyms([finding]).passed

    def test_a_complaint_identifier_is_not_an_acronym(self):
        """The ``CMP`` prefix of an identifier is not jargon to expand."""
        finding = make_finding("Customers said so in CMP-2026W31-0541.")
        assert checks.check_no_unexplained_acronyms([finding]).passed
