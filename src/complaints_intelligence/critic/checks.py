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
``citations_present``         Invariant 2. Two citations, not one: a single
                              complaint is an anecdote.
``citations_resolve``         Offsets must return the text they claim. This is
                              what makes misquotation structurally impossible.
``no_causal_language``        No causal overreach. Correlations stated as
                              correlations.
``no_pii``                    PII is removed before inference; this is the
                              backstop for what redaction missed.
``reading_grade``             The audience includes non-technical committee
                              members.
``no_unexplained_acronyms``   Same reason.
============================  ================================================

``facts_resolve`` and ``citations_resolve`` are assertions, not metrics: they
are expected to pass at 100%, and a failure fails the run.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from complaints_intelligence.config import CriticThresholds
from complaints_intelligence.domain.finding import Claim, Finding
from complaints_intelligence.domain.report import CriticCheck
from complaints_intelligence.store.protocols import ComplaintRepository, FactStore

#: Fact references as they appear in claim text: ``{{f_0142}}``.
FACT_PLACEHOLDER_RE = re.compile(r"\{\{(f_\d{4})\}\}")

#: Any digit not part of a fact placeholder. Deliberately blunt: a report that
#: needs to state a bare number has a fact missing from the metrics layer, and
#: that is a gap to fix upstream rather than an exception to grant here.
_BARE_DIGIT_RE = re.compile(r"\d")

#: Written-out numbers. A model told not to type digits will sometimes write
#: "one hundred and forty-two" instead, which defeats the point.
_NUMBER_WORDS = (
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
    "double",
    "triple",
)
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)

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


def check_no_literal_numbers(findings: Sequence[Finding]) -> CriticCheck:
    """No claim states a figure directly.

    Fact placeholders are stripped before the check, so ``{{f_0142}}`` is
    fine and ``142`` is not. Written-out numbers are caught too: a model told
    not to type digits will otherwise write "one hundred and forty-two".
    """
    offending: list[str] = []
    for finding_id, text, _ in _claim_texts(findings):
        stripped = FACT_PLACEHOLDER_RE.sub("", text)
        if digits := _BARE_DIGIT_RE.findall(stripped):
            offending.append(
                f"{finding_id}: literal digit(s) {''.join(sorted(set(digits)))} "
                f"in claim text"
            )
        if words := _NUMBER_WORD_RE.findall(stripped):
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
        qualitative = bool(FACT_PLACEHOLDER_RE.sub("", text).strip(" .,"))
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


def _syllables(word: str) -> int:
    """Approximate syllable count. Adequate for a readability index."""
    word = word.lower().strip(".,;:!?()'\"")
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    previous_was_vowel = False
    for char in word:
        is_vowel = char in vowels
        if is_vowel and not previous_was_vowel:
            count += 1
        previous_was_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid grade level.

    Implemented here rather than pulled in as a dependency: it is one formula,
    and a readability score is not worth a transitive dependency tree in a
    package whose offline guarantee is a design constraint.
    """
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = [w for w in re.findall(r"[A-Za-z']+", text) if w]
    if not sentences or not words:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return (
        0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59
    )


def check_reading_grade(
    findings: Sequence[Finding], thresholds: CriticThresholds
) -> CriticCheck:
    """Prose is within the configured reading grade."""
    offending: list[str] = []
    for finding in findings:
        text = " ".join(
            [
                finding.headline,
                *(FACT_PLACEHOLDER_RE.sub("a figure", c.text) for c in finding.claims),
            ]
        )
        grade = flesch_kincaid_grade(text)
        if grade > thresholds.max_reading_grade:
            offending.append(
                f"{finding.finding_id}: grade {grade:.1f} exceeds "
                f"{thresholds.max_reading_grade:.1f}"
            )

    return CriticCheck(
        name="reading_grade",
        passed=not offending,
        detail=(
            f"all findings within grade {thresholds.max_reading_grade:.0f}"
            if not offending
            else f"{len(offending)} finding(s) too difficult to read"
        ),
        offending=tuple(offending),
    )


def check_no_unexplained_acronyms(findings: Sequence[Finding]) -> CriticCheck:
    """Internal acronyms are expanded on first use."""
    offending: list[str] = []
    for finding in findings:
        text = " ".join([finding.headline, *(c.text for c in finding.claims)])
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
