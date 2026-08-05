"""Programmatic verification of a draft. No model is involved.

These are assertions about structure and provenance, not judgements about
quality, which is exactly why they can be trusted to gate the render stage: a
model grading another model's output would inherit its failure modes.

===================== ======================================================
Check                 Rationale
===================== ======================================================
``facts_resolve``     Invariant 1. A fact ID that does not exist means a
                      figure was invented.
``no_literal_numbers`` The complement. An ID that resolves proves nothing if
                      the model also typed "142" next to it.
``citations_present`` Invariant 2. Two, not one: one complaint is an anecdote.
``citations_resolve`` Offsets must return the text they claim. This is what
                      makes misquotation structurally impossible.
``no_pii``            Personal data is removed upstream; this is the backstop
                      for what redaction missed.
===================== ======================================================

The first two run over every piece of prose the model wrote that reaches the
reader — findings, rejected-theme rationales and recommendations alike.
``citations_resolve`` covers every span the report quotes. ``citations_present``
is a rule about *claims*: a recommendation is grounded by a named transferable
precedent instead, which the remediate node enforces.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from complaints_intelligence.config import CriticThresholds
from complaints_intelligence.outputs import (
    FACT_PLACEHOLDER_RE,
    Adjudication,
    Citation,
    Claim,
    CriticCheck,
    CriticReport,
    Finding,
    Remediation,
)
from complaints_intelligence.store import Store

#: Identifiers a claim may legitimately name. Stripped before the digit and
#: number-word checks, so a finding about theme CT-007 does not fail for the
#: digits in its own subject.
_IDENTIFIER_RE = re.compile(r"\b(?:CMP-\d{4}W\d{2}-\d{4}|CT-\d{3})\b")

#: Any digit outside a fact placeholder. Deliberately blunt: a report needing a
#: bare number has a fact missing from the metrics layer, which is a gap to fix
#: upstream rather than an exception to grant here.
_BARE_DIGIT_RE = re.compile(r"\d")

#: Written-out numbers, because a model told not to type digits will otherwise
#: write "one hundred and forty-two". Small cardinals are absent on purpose:
#: "one customer noted that…" is how a person writes, not a figure.
_NUMBER_WORD_RE = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|dozen)\b",
    re.IGNORECASE,
)

#: Over-inclusive on purpose: a false positive costs one revision round, a
#: false negative puts a customer's phone number in front of a committee.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("uk_mobile", re.compile(r"\b0?7\d{3}\s?\d{6}\b")),
    ("sort_code", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("account_number", re.compile(r"\b\d{8}\b")),
    ("postcode", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")),
    ("date_of_birth", re.compile(r"\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b")),
)


def strip_references(text: str) -> str:
    """Remove fact placeholders and identifiers, leaving what the model
    actually asserted in its own words."""
    return _IDENTIFIER_RE.sub("", FACT_PLACEHOLDER_RE.sub("", text))


def _claims(findings: Sequence[Finding]) -> list[tuple[str, str, Claim]]:
    """Flatten findings to ``(finding_id, claim_text, claim)`` triples."""
    return [(f.finding_id, c.text, c) for f in findings for c in f.claims]


def _check(name: str, offending: list[str], clean: str, failed: str) -> CriticCheck:
    return CriticCheck(
        name=name,
        passed=not offending,
        detail=clean if not offending else failed.format(n=len(offending)),
        offending=tuple(offending),
    )


def published_prose(
    findings: Sequence[Finding],
    adjudications: Sequence[Adjudication],
    remediations: Sequence[Remediation] = (),
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Everything the model wrote that reaches the reader, as
    ``(location, text, declared_fact_refs)``.

    Adjudication rationales and recommendations are included because neither is
    a finding, yet both are published — a *rejected* theme's rationale appears
    in section 3 and a recommendation in section 4, so checking findings alone
    would leave that prose unverified.

    Remediations are located as ``remediation <finding_id>`` rather than by the
    finding's own ID: the revise node redrafts findings, so attributing a
    recommendation's failure to one would spend the revision budget redrafting
    prose that is not at fault.
    """
    prose: list[tuple[str, str, tuple[str, ...]]] = [
        (f.finding_id, c.text, c.fact_refs) for f in findings for c in f.claims
    ]
    prose += [(a.theme_id, a.rationale, ()) for a in adjudications]
    prose += [
        (f"remediation {r.finding_id}", r.recommendation, r.fact_refs)
        for r in remediations
    ]
    return prose


def cited_spans(
    findings: Sequence[Finding], remediations: Sequence[Remediation] = ()
) -> list[tuple[str, Citation]]:
    """Every citation that reaches the reader, as ``(location, citation)``.

    Shared by the offset check and the PII scan so the two cannot disagree
    about which spans the report actually quotes.
    """
    spans: list[tuple[str, Citation]] = [
        (f.finding_id, citation)
        for f in findings
        for claim in f.claims
        for citation in claim.citations
    ]
    spans += [
        (f"remediation {r.finding_id}", citation)
        for r in remediations
        for citation in r.citations
    ]
    return spans


def check_facts_resolve(
    prose: Sequence[tuple[str, str, tuple[str, ...]]], store: Store
) -> CriticCheck:
    """Every referenced fact ID exists in the fact store.

    Covers both the declared ``fact_refs`` and IDs embedded in the text,
    because the render stage substitutes from the text.
    """
    offending: list[str] = []
    for location, text, fact_refs in prose:
        referenced = set(fact_refs) | set(FACT_PLACEHOLDER_RE.findall(text))
        offending += [
            f"{location}: {fact_id} does not resolve"
            for fact_id in sorted(referenced)
            if not store.fact_exists(fact_id)
        ]
    return _check(
        "facts_resolve",
        offending,
        "every referenced fact ID resolves in the fact store",
        "{n} unresolvable fact reference(s)",
    )


def check_no_literal_numbers(
    prose: Sequence[tuple[str, str, tuple[str, ...]]],
) -> CriticCheck:
    """No published sentence states a figure directly. Placeholders are
    stripped first, so ``{{f_0142}}`` is fine and ``142`` is not."""
    offending: list[str] = []
    for location, text, _ in prose:
        stripped = strip_references(text)
        if digits := _BARE_DIGIT_RE.findall(stripped):
            offending.append(
                f"{location}: literal digit(s) {''.join(sorted(set(digits)))}"
            )
        if words := _NUMBER_WORD_RE.findall(stripped):
            offending.append(
                f"{location}: number word(s) {sorted({w.lower() for w in words})}"
            )
    return _check(
        "no_literal_numbers",
        offending,
        "no published sentence states a figure directly",
        "{n} sentence(s) contain a literal figure",
    )


def check_citations_present(
    findings: Sequence[Finding], thresholds: CriticThresholds
) -> CriticCheck:
    """Every qualitative claim carries enough citations.

    A claim that only references facts is exempt — the fact store already
    supports it — and so is a hypothesis, which is published explicitly as
    unconfirmed and would be unusable if it had to be evidenced.
    """
    minimum = thresholds.min_citations_per_claim
    offending: list[str] = []
    for finding_id, text, claim in _claims(findings):
        if claim.requires_confirmation:
            continue
        if not strip_references(text).strip(" .,"):
            continue
        if len(claim.citations) < minimum:
            offending.append(
                f"{finding_id}: {len(claim.citations)} citation(s), needs "
                f"{minimum} — {text[:60]!r}"
            )
    return _check(
        "citations_present",
        offending,
        f"every qualitative claim carries at least {minimum} citations",
        "{n} claim(s) under-cited",
    )


def check_citations_resolve(
    spans: Sequence[tuple[str, Citation]], store: Store
) -> CriticCheck:
    """Every citation resolves to real text at the offsets given.

    This is what makes misquotation structurally impossible: the renderer pulls
    the quote from the store using these offsets, so a citation that fails here
    would produce a quote that does not exist.
    """
    offending: list[str] = []
    for location, citation in spans:
        try:
            complaint = store.get_complaint(citation.complaint_id)
        except KeyError:
            offending.append(f"{location}: no complaint {citation.complaint_id!r}")
            continue
        if citation.end > len(complaint.text) or citation.start >= citation.end:
            offending.append(
                f"{location}: {citation.complaint_id} offsets "
                f"{citation.start}:{citation.end} fall outside text of "
                f"length {len(complaint.text)}"
            )
    return _check(
        "citations_resolve",
        offending,
        "every citation resolves to source text",
        "{n} unresolvable citation(s)",
    )


def check_no_pii(texts: Sequence[tuple[str, str]]) -> CriticCheck:
    """No personal data in output text.

    Run over the resolved quotations as well as the model's own prose: a quote
    pulled from the store can carry an identifier redaction missed.
    """
    offending = [
        f"{location}: possible {label}"
        for location, text in texts
        for label, pattern in _PII_PATTERNS
        if pattern.search(text)
    ]
    return _check(
        "no_pii",
        offending,
        "no personal data detected in output",
        "{n} possible PII occurrence(s)",
    )


def verify(
    findings: Sequence[Finding],
    *,
    adjudications: Sequence[Adjudication],
    remediations: Sequence[Remediation],
    store: Store,
    thresholds: CriticThresholds,
    revision: int,
    scanned_texts: Sequence[tuple[str, str]],
) -> CriticReport:
    """Run every check and collect the verdict."""
    prose = published_prose(findings, adjudications, remediations)
    return CriticReport(
        checks=(
            check_facts_resolve(prose, store),
            check_no_literal_numbers(prose),
            # Claims only. A recommendation's grounding is a named transferable
            # precedent, enforced in the remediate node, not a citation count.
            check_citations_present(findings, thresholds),
            check_citations_resolve(cited_spans(findings, remediations), store),
            check_no_pii(scanned_texts),
        ),
        revision=revision,
    )
