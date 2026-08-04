"""Rendering: fact substitution, quotation resolution, and presentation.

The renderer is where invariants 1 and 2 are actually delivered, so its
behaviour on model output that is *nearly* right matters as much as its
behaviour on output that is correct.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.domain.finding import Citation
from complaints_intelligence.errors import ProvenanceError
from complaints_intelligence.render.renderer import (
    _snap_to_words,
    resolve_quote,
    resolve_text,
)
from complaints_intelligence.store.duckdb_store import DuckDBStore


class TestFactSubstitution:
    def test_a_double_braced_placeholder_resolves(self, store: DuckDBStore):
        fact = store.all_facts()[0]
        out = resolve_text(f"Volumes reached {{{{{fact.id}}}}}.", store)
        assert fact.render() in out
        assert fact.id not in out

    def test_a_single_braced_placeholder_also_resolves(self, store: DuckDBStore):
        """Lenient on the delimiter, strict on the value.

        Models reliably choose the right fact ID and unreliably count braces.
        """
        fact = store.all_facts()[0]
        out = resolve_text(f"Volumes reached {{{fact.id}}}.", store)
        assert fact.render() in out

    def test_an_unresolvable_fact_raises_when_verification_passed(
        self, store: DuckDBStore
    ):
        """The store changed under a verified run. Stop, do not print a gap."""
        with pytest.raises(ProvenanceError, match="did not resolve at render time"):
            resolve_text("Volumes reached {{f_9999}}.", store, strict=True)

    def test_an_unresolvable_fact_survives_visibly_when_verification_failed(
        self, store: DuckDBStore
    ):
        """The placeholder is the evidence of the failure.

        Critically, it is left visible rather than substituted, so no reader
        can mistake it for a figure.
        """
        out = resolve_text("Volumes reached {{f_9999}}.", store, strict=False)
        assert "{{f_9999}}" in out

    def test_braces_around_an_identifier_are_stripped(self, store: DuckDBStore):
        """The model sometimes imitates placeholder syntax on a complaint ID.

        It is a reference, not a figure, so it should read as one rather than
        as an unresolved placeholder.
        """
        out = resolve_text("As seen in {CMP-2026W31-0546} and {CT-007}.", store)
        assert "CMP-2026W31-0546" in out
        assert "CT-007" in out
        assert "{" not in out


class TestQuotationResolution:
    @pytest.mark.parametrize(
        ("text", "span", "expected"),
        [
            # Ends mid-word: "faile" -> "failed".
            ("the transfer failed without explanation", (4, 17), (4, 19)),
            # Starts and ends mid-word: "aymen" -> "payment".
            ("payment did not arrive", (1, 6), (0, 7)),
            # Already on boundaries: unchanged.
            ("the transfer failed", (0, 3), (0, 3)),
            ("the transfer failed without explanation", (4, 20), (4, 20)),
        ],
    )
    def test_spans_widen_to_word_boundaries(
        self, text: str, span: tuple[int, int], expected: tuple[int, int]
    ):
        assert _snap_to_words(text, *span) == expected

    def test_widening_never_narrows(self):
        """The quotation can gain the rest of a word, never lose sense."""
        text = "the transfer failed without any explanation at all"
        for start in range(0, len(text) - 5, 3):
            for end in range(start + 1, min(start + 25, len(text))):
                new_start, new_end = _snap_to_words(text, start, end)
                assert new_start <= start
                assert new_end >= end

    def test_a_quote_is_a_slice_of_stored_text(self, store: DuckDBStore):
        """Invariant 2: the model never handles the words it quotes."""
        complaint = store.exemplars(
            query_text="payment failed", week="2026-W31", limit=1
        )[0]
        citation = Citation(complaint_id=complaint.complaint_id, start=3, end=25)
        resolved = resolve_quote(citation, store)
        assert resolved.text
        assert resolved.text in resolved.complaint.text

    def test_a_quote_does_not_end_mid_word(self, store: DuckDBStore):
        complaint = store.exemplars(
            query_text="payment failed", week="2026-W31", limit=1
        )[0]
        citation = Citation(complaint_id=complaint.complaint_id, start=3, end=20)
        quote = resolve_quote(citation, store).text
        assert not quote.endswith(("explanat", "explana"))
        # The character after the quote in the source is whitespace or the end.
        index = complaint.text.index(quote) + len(quote)
        assert index >= len(complaint.text) or not complaint.text[index].isalpha()

    def test_offsets_past_the_end_are_clamped(self, store: DuckDBStore):
        complaint = store.exemplars(
            query_text="payment failed", week="2026-W31", limit=1
        )[0]
        citation = Citation(complaint_id=complaint.complaint_id, start=0, end=99_000)
        quote = resolve_quote(citation, store).text
        # Clamped to the stored text. A long complaint is then truncated for
        # the report, so the ellipsis is expected and is not stored text.
        assert complaint.text.startswith(quote.removesuffix("…"))

    @pytest.mark.parametrize(
        ("start", "end"),
        [(3, 25), (0, 12), (9, 57), (17, 18), (0, 99_000), (40, 41)],
    )
    def test_the_published_offsets_produce_the_published_quote(
        self, store: DuckDBStore, start: int, end: int
    ):
        """The range printed beside a quotation must be the range that yields it.

        The offsets are what a reviewer uses to check a quotation against the
        source. Publishing the model's requested span while printing a widened
        one made every citation label subtly wrong — two citations in the same
        report claimed the same range for quotations of different lengths.
        """
        complaint = store.exemplars(
            query_text="payment failed", week="2026-W31", limit=1
        )[0]
        citation = Citation(complaint_id=complaint.complaint_id, start=start, end=end)
        resolved = resolve_quote(citation, store)

        printed = resolved.text.removesuffix("…")
        assert complaint.text[resolved.start : resolved.end] == printed

    @pytest.mark.parametrize(("start", "end"), [(9, 57), (3, 25), (17, 30)])
    def test_the_quote_still_contains_everything_cited(
        self, store: DuckDBStore, start: int, end: int
    ):
        """Adjusting the span for whitespace must not drop cited content.

        The published span moves inward when the widened slice begins or ends
        on whitespace. That is presentation only — the words the model cited
        all survive, which is what stops the offset bookkeeping from quietly
        narrowing a quotation and changing its sense.
        """
        complaint = store.exemplars(
            query_text="payment failed", week="2026-W31", limit=1
        )[0]
        citation = Citation(complaint_id=complaint.complaint_id, start=start, end=end)
        resolved = resolve_quote(citation, store)

        cited = complaint.text[start:end].strip()
        assert cited in resolved.text
