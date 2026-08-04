"""Deterministic rendering. No model involvement.

This is where figures and quotations enter the report, and it is the reason
numeric hallucination and misquotation are structurally impossible rather than
detected after the fact:

- A claim's text contains ``{{f_0142}}``, never a number. The value is looked
  up in the fact store here. A placeholder that does not resolve raises rather
  than printing.
- A citation is a complaint ID and a character range. The quotation is sliced
  out of the stored text here. The model never handles the words it quotes, so
  it cannot alter them.

Rendering runs after the graph, against verified state, so it is outside the
reach of any revision loop. The one stage that must never vary is the one that
substitutes real figures into prose.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import NamedTuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from complaints_intelligence.config import PACKAGE_ROOT
from complaints_intelligence.domain.brief import SentimentSignal
from complaints_intelligence.domain.complaint import ComplaintEnvelope
from complaints_intelligence.domain.finding import (
    FACT_PLACEHOLDER_RE,
    Adjudication,
    Citation,
    Finding,
    Remediation,
)
from complaints_intelligence.domain.report import Report
from complaints_intelligence.errors import ProvenanceError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.render.spans import clamp_and_snap, snap_to_words
from complaints_intelligence.store.protocols import ComplaintRepository, FactStore
from complaints_intelligence.synth.taxonomy import display_name

log = get_logger(__name__)

#: Kept as a module-level name here because the span arithmetic is part of the
#: renderer's contract even though it now lives with the critic's copy.
_snap_to_words = snap_to_words

_TEMPLATE_DIR = PACKAGE_ROOT / "render" / "templates"

#: Shared with the critic, so verification and rendering cannot disagree
#: about what counts as a fact reference.
_PLACEHOLDER_RE = FACT_PLACEHOLDER_RE

#: Complaint or theme identifiers the model wrapped in braces, imitating the
#: fact-placeholder syntax. The prompts ask it not to write identifiers into
#: prose at all; when it does anyway, the braces are stripped so the reference
#: reads as a reference rather than as an unresolved placeholder.
_BRACED_IDENTIFIER_RE = re.compile(
    r"\{\{?((?:[A-Z]{2,5}-\d{4}W\d{2}-\d{4}|CT-\d{3}))\}\}?"
)

#: Quotations longer than this are truncated in the rendered report. The full
#: span remains in the report object, so the drill-down is unaffected.
_MAX_QUOTE_CHARS = 220


def resolve_text(text: str, facts: FactStore, *, strict: bool = True) -> str:
    """Substitute fact placeholders with their stored values.

    ``strict`` follows the critic's verdict, and the two cases are genuinely
    different:

    - **Verification passed.** Every reference was checked moments ago, so an
      unresolvable ID means the fact store changed under the run. That must
      stop the report rather than leave a gap in it.
    - **Verification failed.** The report is already marked unpublishable, and
      the unresolved placeholder is the *evidence* of what went wrong. Raising
      here would destroy the artefact a reviewer needs in order to see why the
      run failed. The placeholder is left visible — and because it is left
      visible rather than substituted, no reader can mistake it for a figure.
    """

    def substitute(match: re.Match[str]) -> str:
        fact_id = match.group(1)
        try:
            return facts.get_fact(fact_id).render()
        except ProvenanceError:
            if not strict:
                return match.group(0)
            msg = (
                f"fact {fact_id!r} did not resolve at render time although it "
                f"passed verification; the fact store has changed mid-run"
            )
            raise ProvenanceError(msg) from None

    return _BRACED_IDENTIFIER_RE.sub(r"\1", _PLACEHOLDER_RE.sub(substitute, text))


class ResolvedQuote(NamedTuple):
    """A quotation and the span it was actually taken from.

    ``start`` and ``end`` are the *printed* span, not the one the model asked
    for: clamped into the text, widened to word boundaries, then narrowed again
    by whatever stripping and truncation the quotation underwent. The invariant
    a reader depends on is ``complaint.text[start:end] == text`` — the range
    printed beside a quotation must be the range that produces it.

    The model's original offsets are untouched on the ``Citation`` carried by
    the report object, so the drill-down is unaffected.
    """

    text: str
    complaint: ComplaintEnvelope
    start: int
    end: int


def resolve_quote(citation: Citation, complaints: ComplaintRepository) -> ResolvedQuote:
    """Pull the quoted span out of the stored complaint text."""
    complaint = complaints.get_complaint(citation.complaint_id)
    start, end = clamp_and_snap(complaint.text, citation.start, citation.end)

    # Stripping and truncation both change which characters survive into the
    # report, so both have to move the published span with them. Tracking the
    # offsets through each step is what keeps the printed range honest.
    raw = complaint.text[start:end]
    start += len(raw) - len(raw.lstrip())
    end -= len(raw) - len(raw.rstrip())
    quote = complaint.text[start:end]

    if len(quote) > _MAX_QUOTE_CHARS:
        truncated = quote[: _MAX_QUOTE_CHARS - 1].rstrip()
        end = start + len(truncated)
        # The ellipsis is a rendering mark rather than quoted text, so it sits
        # outside the span the offsets describe.
        return ResolvedQuote(truncated + "…", complaint, start, end)

    return ResolvedQuote(quote, complaint, start, end)


class RenderedCitation:
    """A citation with its quote and channel resolved, ready for templating."""

    def __init__(self, citation: Citation, complaints: ComplaintRepository) -> None:
        resolved = resolve_quote(citation, complaints)
        self.complaint_id = citation.complaint_id
        self.start = resolved.start
        self.end = resolved.end
        self.quote = resolved.text
        self.channel = resolved.complaint.channel.value
        self.week = resolved.complaint.week


class RenderedClaim:
    """A claim with its figures substituted and citations resolved."""

    def __init__(
        self,
        text: str,
        facts: FactStore,
        complaints: ComplaintRepository,
        *,
        citations: tuple[Citation, ...],
        requires_confirmation: bool,
        strict: bool,
    ) -> None:
        self.text = resolve_text(text, facts, strict=strict)
        self.requires_confirmation = requires_confirmation
        self.citations = [
            RenderedCitation(c, complaints)
            for c in citations
            if _resolvable(c, complaints)
        ]


def _resolvable(citation: Citation, complaints: ComplaintRepository) -> bool:
    """Whether a citation can be quoted at all.

    Only reached on a report that already failed verification — a passing
    report has had every citation checked. Skipping the unquotable ones keeps
    the failed draft readable so a reviewer can see what else went wrong.
    """
    try:
        complaint = complaints.get_complaint(citation.complaint_id)
    except KeyError:
        return False
    return citation.start < len(complaint.text)


class RenderedFinding:
    """A finding ready for templating."""

    def __init__(
        self,
        finding: Finding,
        facts: FactStore,
        complaints: ComplaintRepository,
        *,
        strict: bool = True,
    ) -> None:
        self.finding_id = finding.finding_id
        self.kind = finding.kind.value
        self.headline = resolve_text(finding.headline, facts, strict=strict)
        self.category = finding.category
        self.category_display = (
            display_name(finding.category) if finding.category else None
        )
        self.theme_id = finding.theme_id
        self.claims = [
            RenderedClaim(
                claim.text,
                facts,
                complaints,
                citations=claim.citations,
                requires_confirmation=claim.requires_confirmation,
                strict=strict,
            )
            for claim in finding.claims
        ]

    @property
    def evidenced_claims(self) -> list[RenderedClaim]:
        return [c for c in self.claims if not c.requires_confirmation]

    @property
    def hypotheses(self) -> list[RenderedClaim]:
        return [c for c in self.claims if c.requires_confirmation]


class RenderedAdjudication:
    """An adjudication with its figures substituted.

    The rationale is published prose and is subject to the same resolution as
    any claim. Rendering it raw left `{f_0191}` visible in the report — a
    figure the reader could not read and the store never supplied.
    """

    def __init__(
        self, adjudication: Adjudication, facts: FactStore, *, strict: bool = True
    ) -> None:
        self.theme_id = adjudication.theme_id
        self.verdict = adjudication.verdict.value.replace("_", " ")
        self.rationale = resolve_text(adjudication.rationale, facts, strict=strict)
        self.duplicate_of_category = adjudication.duplicate_of_category


class RenderedRemediation:
    """A remediation ready for templating."""

    def __init__(
        self,
        remediation: Remediation,
        facts: FactStore,
        complaints: ComplaintRepository,
        *,
        strict: bool = True,
    ) -> None:
        self.finding_id = remediation.finding_id
        self.recommendation = resolve_text(
            remediation.recommendation, facts, strict=strict
        )
        self.suggested_owner = remediation.suggested_owner
        self.citations = [
            RenderedCitation(c, complaints)
            for c in remediation.citations
            if _resolvable(c, complaints)
        ]
        # Precedents that did not transfer are kept and shown. A report that
        # says what it ruled out, and why, is auditable; one that shows only
        # what supported its conclusion is advocacy.
        self.transferring = [p for p in remediation.precedents if p.transfers]
        self.rejected = [p for p in remediation.precedents if not p.transfers]


class RenderedSentiment:
    """One within-channel sentiment shift, ready for templating.

    No model touched any part of this. The three figures are looked up by fact
    ID exactly as a claim's placeholders are, so the section is subject to the
    same provenance rule as the rest of the report while requiring none of the
    machinery that exists to constrain model output.

    Resolution is unconditionally strict. These IDs come from the metrics
    layer, never from a model, so there is no unverified-draft case to be
    lenient about: one that fails to resolve means the fact store changed under
    the run, which must stop the report rather than leave a gap in it.
    """

    def __init__(self, signal: SentimentSignal, facts: FactStore) -> None:
        self.scope = signal.scope
        self.scope_display = display_name(signal.scope)
        self.channel = signal.channel
        self.channel_display = (
            signal.channel.replace("_", " ") if signal.channel else "all channels"
        )
        self.direction = signal.direction.value
        self.current = facts.get_fact(signal.current_fact_id).render()
        self.baseline = facts.get_fact(signal.baseline_fact_id).render()
        self.shift = facts.get_fact(signal.shift_fact_id).render()


def render_markdown(
    report: Report,
    *,
    facts: FactStore,
    complaints: ComplaintRepository,
) -> str:
    """Render the report object to Markdown."""
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - Markdown output, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = environment.get_template("report.md.j2")

    # A verified report must resolve completely or stop. An unverified one is
    # already marked unpublishable, and rendering it — placeholders and all —
    # is what lets a reviewer see why it failed.
    strict = report.critic.passed

    output: str = template.render(
        report=report,
        drivers=[
            RenderedFinding(f, facts, complaints, strict=strict) for f in report.drivers
        ],
        sentiment=[RenderedSentiment(s, facts) for s in report.sentiment],
        emerging=[
            RenderedFinding(f, facts, complaints, strict=strict)
            for f in report.emerging
        ],
        remediations=[
            RenderedRemediation(r, facts, complaints, strict=strict)
            for r in report.remediations
        ],
        adjudications=[
            RenderedAdjudication(a, facts, strict=strict) for a in report.adjudications
        ],
        generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    log.info(
        "report_rendered",
        run_id=report.run_id,
        chars=len(output),
        strict=strict,
    )
    return output


def utc_now() -> datetime:
    """Current UTC time. One place, so tests can patch it."""
    return datetime.now(UTC)
