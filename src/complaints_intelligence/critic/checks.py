"""Programmatic verification of a draft. No model is involved.

These are assertions about structure and provenance, not judgements about
quality — which is exactly why they can be trusted to gate the render stage.
A model grading another model's output would inherit its failure modes; a
regular expression and a lookup in the fact store do not.

What is enforced, and why each one is here:

============================  ================================================
Check                         Rationale
============================  ================================================
``facts_resolve``             Invariant 1. A fact ID that does not exist means
                              a figure was invented.
``no_literal_numbers``        The complement of the above. An ID that resolves
                              proves nothing if the model also typed "142"
                              next to it.
``fact_placement``            Substitution happens after verification, so
                              nothing else looks at the result. A legitimate
                              reference in the wrong slot renders as
                              "...attempts were rejected 131."
``citations_present``         Invariant 2. Two citations, not one: a single
                              complaint is an anecdote.
``citations_resolve``         Offsets must return the text they claim. This is
                              what makes misquotation structurally impossible.
``no_causal_language``        No causal overreach. Correlations stated as
                              correlations.
``no_pii``                    PII is removed before inference; this is the
                              backstop for what redaction missed.
``no_unexplained_acronyms``   The audience includes non-technical committee
                              members.
============================  ================================================

``facts_resolve`` and ``citations_resolve`` are assertions, not metrics: they
are expected to pass at 100%, and a failure fails the run.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from complaints_intelligence.config import CriticThresholds
from complaints_intelligence.domain.finding import (
    FACT_PLACEHOLDER_RE as _FACT_PLACEHOLDER_RE,
)
from complaints_intelligence.domain.finding import Claim, Finding
from complaints_intelligence.domain.report import CriticCheck
from complaints_intelligence.store.protocols import ComplaintRepository, FactStore

#: Re-exported so the critic and the renderer share one definition of what a
#: fact reference looks like. See ``domain.finding``.
FACT_PLACEHOLDER_RE = _FACT_PLACEHOLDER_RE

#: Identifiers a claim may legitimately name: complaint IDs and theme IDs.
#:
#: These are *references*, not figures, and they are stripped before the
#: digit, number-word and acronym checks run. Without this, a finding about
#: theme ``CT-007`` fails ``no_literal_numbers`` for the digits in its own
#: subject, and a rationale that names a complaint fails
#: ``no_unexplained_acronyms`` on the ``CMP`` prefix — neither of which is the
#: problem those checks exist to catch.
_IDENTIFIER_RE = re.compile(r"\b(?:[A-Z]{2,5}-\d{4}W\d{2}-\d{4}|CT-\d{3})\b")


def strip_references(text: str) -> str:
    """Remove fact placeholders and identifiers, leaving prose.

    What remains is what the model actually asserted in its own words, which
    is what the prose checks should be judging.
    """
    return _IDENTIFIER_RE.sub("", FACT_PLACEHOLDER_RE.sub("", text))


#: Any digit not part of a fact placeholder. Deliberately blunt: a report that
#: needs to state a bare number has a fact missing from the metrics layer, and
#: that is a gap to fix upstream rather than an exception to grant here.
_BARE_DIGIT_RE = re.compile(r"\d")

#: The last word before a fact reference, for the placement check.
_LAST_WORD_RE = re.compile(r"(\w+)\W*$")

#: Words after which a bare figure reads correctly, so a reference may end a
#: clause. Everything else trailing a clause renders as "...rejected 131."
_FIGURE_INTRODUCERS = frozenset(
    {
        "to",
        "of",
        "at",
        "by",
        "from",
        "reached",
        "rose",
        "fell",
        "was",
        "were",
        "spans",
        "covers",
        "totalled",
        "across",
        "among",
        "under",
        "over",
        "is",
        "are",
    }
)

# Written-out numbers. A model told not to type digits will otherwise write
# "one hundred and forty-two" instead, which defeats the point.
#
# Two tiers, because a single word list has an unacceptable false-positive
# rate on ordinary English. "One customer noted that…" is not a figure; it is
# how a person writes. Flagging it costs a revision round and pushes the
# report towards stilted prose, which is the opposite of what the report is
# for.

#: Always a quantity, whatever the context.
_SCALE_WORDS = (
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "dozen",
    "half",
    "third",
    "quarter",
)
_SCALE_WORD_RE = re.compile(r"\b(" + "|".join(_SCALE_WORDS) + r")\b", re.IGNORECASE)

#: Small cardinals, which are quantities only when they are counting
#: something. Flagged when followed by a plural noun ("twelve complaints")
#: and allowed as determiners ("one customer described").
_SMALL_CARDINALS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
)
_COUNTING_RE = re.compile(
    r"\b(" + "|".join(_SMALL_CARDINALS) + r")\s+(?=[a-z]+s\b)", re.IGNORECASE
)

# "double" and "triple" are deliberately absent from both tiers. In complaint
# language they are overwhelmingly descriptive — a "double debit" is the name
# of the fault, not a quantity — and flagging them forces the report to
# describe the problem in worse English than the customers used.

#: Causal assertions. "Coincident with" is permitted; these are not.
_CAUSAL_RE = re.compile(
    r"\b("
    r"caused by|causes|causing|because of|because|due to|led to|leads to|"
    r"resulted in|results in|resulting from|as a result of|"
    r"stems from|stemming from|attributable to|owing to|"
    r"the reason (?:is|was|for)|driven by|triggered by"
    r")\b",
    re.IGNORECASE,
)

#: PII patterns. Deliberately over-inclusive: a false positive costs one
#: revision loop, a false negative puts a customer's phone number in a
#: document that goes to a committee.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("uk_mobile", re.compile(r"\b0?7\d{3}\s?\d{6}\b")),
    ("uk_landline", re.compile(r"\b0[12]\d{2,3}\s?\d{6,7}\b")),
    ("sort_code", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("account_number", re.compile(r"\b\d{8}\b")),
    ("postcode", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")),
    ("date_of_birth", re.compile(r"\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b")),
    ("national_insurance", re.compile(r"\b[A-Z]{2}\d{6}[A-D]\b")),
)

#: Acronyms a compliance audience is assumed to know. Anything else must be
#: expanded on first use.
_KNOWN_ACRONYMS = frozenset(
    {
        "FCA",
        "FOS",
        "PRA",
        "DISP",
        "SMF",
        "MI",
        "UK",
        "AI",
        "ML",
        "ATM",
        "PIN",
        "DD",
        "SLA",
        "PDF",
        "CT",
    }
)
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")


def _claim_texts(findings: Sequence[Finding]) -> list[tuple[str, str, Claim]]:
    """Flatten findings to ``(finding_id, claim_text, claim)`` triples."""
    return [(f.finding_id, c.text, c) for f in findings for c in f.claims]


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


def check_facts_resolve(findings: Sequence[Finding], facts: FactStore) -> CriticCheck:
    """Every referenced fact ID exists in the run's fact store.

    Covers both the ``fact_refs`` list and IDs embedded in claim text, because
    a model can reference one without declaring the other and the render stage
    substitutes from the text.
    """
    offending: list[str] = []
    for finding_id, text, claim in _claim_texts(findings):
        referenced = set(claim.fact_refs) | set(FACT_PLACEHOLDER_RE.findall(text))
        for fact_id in sorted(referenced):
            if not facts.fact_exists(fact_id):
                offending.append(f"{finding_id}: {fact_id} does not resolve")

    return CriticCheck(
        name="facts_resolve",
        passed=not offending,
        detail=(
            "every referenced fact ID resolves in the fact store"
            if not offending
            else f"{len(offending)} unresolvable fact reference(s)"
        ),
        offending=tuple(offending),
    )


def check_fact_placement(findings: Sequence[Finding]) -> CriticCheck:
    """A fact reference sits where a number can grammatically stand.

    The other fact checks ask whether a reference is *legitimate*. This one
    asks whether the sentence still reads once it becomes a figure, because
    substitution happens after verification and nothing else looks at the
    result. A trailing reference passes every other check and renders as
    "...multiple attempts were rejected 131."

    The rule is narrow on purpose. A reference is well placed when a word
    follows it — the noun it counts — or when the word before it is one that
    introduces a figure. It fails only when the reference ends a clause with
    no such word before it, which is the shape all the observed defects took
    and none of the correct usages did.
    """
    offending: list[str] = []
    for finding_id, text, _ in _claim_texts(findings):
        for match in FACT_PLACEHOLDER_RE.finditer(text):
            trailing = text[match.end() :].lstrip()
            if trailing and trailing[0] not in ".,;:)":
                continue  # A noun follows; the figure has something to count.

            preceding = _LAST_WORD_RE.search(text[: match.start()])
            if preceding and preceding.group(1).lower() in _FIGURE_INTRODUCERS:
                continue

            offending.append(
                f"{finding_id}: {match.group(1)} ends a clause with nothing to "
                f"count; it will render as a bare number"
            )

    return CriticCheck(
        name="fact_placement",
        passed=not offending,
        detail=(
            "every fact reference sits where a figure reads correctly"
            if not offending
            else f"{len(offending)} fact reference(s) would render as a bare number"
        ),
        offending=tuple(offending),
    )


def check_no_literal_numbers(findings: Sequence[Finding]) -> CriticCheck:
    """No claim states a figure directly.

    Fact placeholders are stripped before the check, so ``{{f_0142}}`` is
    fine and ``142`` is not. Written-out numbers are caught too: a model told
    not to type digits will otherwise write "one hundred and forty-two".
    """
    offending: list[str] = []
    for finding_id, text, _ in _claim_texts(findings):
        stripped = strip_references(text)
        if digits := _BARE_DIGIT_RE.findall(stripped):
            offending.append(
                f"{finding_id}: literal digit(s) {''.join(sorted(set(digits)))} "
                f"in claim text"
            )
        words = _SCALE_WORD_RE.findall(stripped) + _COUNTING_RE.findall(stripped)
        if words:
            offending.append(
                f"{finding_id}: number word(s) {sorted({w.lower() for w in words})}"
            )

    return CriticCheck(
        name="no_literal_numbers",
        passed=not offending,
        detail=(
            "no claim states a figure directly"
            if not offending
            else f"{len(offending)} claim(s) contain a literal figure"
        ),
        offending=tuple(offending),
    )


def check_citations_present(
    findings: Sequence[Finding], thresholds: CriticThresholds
) -> CriticCheck:
    """Every qualitative claim carries enough citations.

    Two rather than one, because a single complaint is an anecdote. A claim
    that only references facts and asserts nothing qualitative is exempt —
    "volumes rose to {{f_0142}}" needs no complaint to support it, the fact
    store already does.
    """
    minimum = thresholds.min_citations_per_claim
    offending: list[str] = []
    for finding_id, text, claim in _claim_texts(findings):
        # Hypotheses are exempt, for the same reason they are exempt from the
        # causal-language check: they are published explicitly as unconfirmed
        # and requiring a named owner. A hypothesis is by nature a step beyond
        # what the evidence shows, so demanding evidence for it would make the
        # mechanism unusable — and an unusable hypothesis field pushes causal
        # speculation back into the claims, which is the outcome this design
        # exists to prevent.
        if claim.requires_confirmation:
            continue
        qualitative = bool(strip_references(text).strip(" .,"))
        if not qualitative:
            continue
        if len(claim.citations) < minimum:
            offending.append(
                f"{finding_id}: {len(claim.citations)} citation(s), "
                f"needs {minimum} — {text[:60]!r}"
            )

    return CriticCheck(
        name="citations_present",
        passed=not offending,
        detail=(
            f"every qualitative claim carries at least {minimum} citations"
            if not offending
            else f"{len(offending)} claim(s) under-cited"
        ),
        offending=tuple(offending),
    )


def check_citations_resolve(
    findings: Sequence[Finding], complaints: ComplaintRepository
) -> CriticCheck:
    """Every citation resolves to real text at the offsets given.

    This is what makes misquotation structurally impossible rather than
    detected after the fact: the render stage pulls the quote from the store
    using these offsets, so a citation that does not resolve here would
    produce a quote that does not exist.
    """
    offending: list[str] = []
    for finding in findings:
        for claim in finding.claims:
            for citation in claim.citations:
                try:
                    complaint = complaints.get_complaint(citation.complaint_id)
                except KeyError:
                    offending.append(
                        f"{finding.finding_id}: no complaint {citation.complaint_id!r}"
                    )
                    continue
                if citation.end > len(complaint.text) or citation.start >= citation.end:
                    offending.append(
                        f"{finding.finding_id}: {citation.complaint_id} offsets "
                        f"{citation.start}:{citation.end} outside text of length "
                        f"{len(complaint.text)}"
                    )

    return CriticCheck(
        name="citations_resolve",
        passed=not offending,
        detail=(
            "every citation resolves to source text"
            if not offending
            else f"{len(offending)} unresolvable citation(s)"
        ),
        offending=tuple(offending),
    )


def check_no_causal_language(findings: Sequence[Finding]) -> CriticCheck:
    """No claim asserts causation.

    Claims marked ``requires_confirmation`` are exempt: those are published
    explicitly as hypotheses needing a named owner, which is the sanctioned
    route for a causal belief.
    """
    offending: list[str] = []
    for finding_id, text, claim in _claim_texts(findings):
        if claim.requires_confirmation:
            continue
        if matches := _CAUSAL_RE.findall(text):
            offending.append(
                f"{finding_id}: causal phrase(s) {sorted({m.lower() for m in matches})}"
            )

    return CriticCheck(
        name="no_causal_language",
        passed=not offending,
        detail=(
            "no unhedged causal assertions"
            if not offending
            else f"{len(offending)} claim(s) assert causation"
        ),
        offending=tuple(offending),
    )


def check_no_pii(texts: Sequence[tuple[str, str]]) -> CriticCheck:
    """No personal data in output text.

    Run over the *rendered* output, including resolved quotations — a quote
    pulled from the store can carry PII that redaction missed, and checking
    only the model's own words would inspect the one part of the report least
    likely to contain any.
    """
    offending: list[str] = []
    for location, text in texts:
        for label, pattern in _PII_PATTERNS:
            if pattern.search(text):
                offending.append(f"{location}: possible {label}")

    return CriticCheck(
        name="no_pii",
        passed=not offending,
        detail=(
            "no personal data detected in output"
            if not offending
            else f"{len(offending)} possible PII occurrence(s)"
        ),
        offending=tuple(offending),
    )


def check_no_unexplained_acronyms(findings: Sequence[Finding]) -> CriticCheck:
    """Internal acronyms are expanded on first use."""
    offending: list[str] = []
    for finding in findings:
        text = strip_references(
            " ".join([finding.headline, *(c.text for c in finding.claims)])
        )
        for acronym in sorted(set(_ACRONYM_RE.findall(text))):
            if acronym in _KNOWN_ACRONYMS:
                continue
            # Treat "Something Or Other (SOO)" as an expansion on first use.
            if f"({acronym})" in text:
                continue
            offending.append(f"{finding.finding_id}: unexplained acronym {acronym!r}")

    return CriticCheck(
        name="no_unexplained_acronyms",
        passed=not offending,
        detail=(
            "no unexplained acronyms"
            if not offending
            else f"{len(offending)} unexplained acronym(s)"
        ),
        offending=tuple(offending),
    )
