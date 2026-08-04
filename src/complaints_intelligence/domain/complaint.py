"""The complaint envelope and its enrichment.

``ComplaintEnvelope`` is the canonical schema every channel is mapped into.
Channel-specific messiness is confined to the adapters (out of scope here);
``channel`` survives as a first-class feature rather than being discarded,
because sentiment and volume both vary systematically by channel.

Records here are generated *as if* they had already passed ingest, PII
redaction, injection screening, classification and enrichment. Those stages
are out of scope for this package; see ``CLAUDE.md``.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Channel(StrEnum):
    """Intake channel. Retained as a feature, not normalised away."""

    FOS_REFERRAL = "fos_referral"
    MOBILE_APP = "mobile_app"
    BRANCH = "branch"
    CALL_CENTRE = "call_centre"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Outcome(StrEnum):
    """Outcome recorded on a closed complaint."""

    UPHELD = "upheld"
    PARTIALLY_UPHELD = "partially_upheld"
    NOT_UPHELD = "not_upheld"


class RoutingDecision(StrEnum):
    """Which track the enriched record was sent down.

    ``ASSIGN`` records feed the attribution track and the trend numbers.
    ``ABSTAIN`` records form the residual pool and feed theme discovery.

    Abstention is a deliberate refusal, not a failure. Abstained complaints
    still count in totals but do not contribute to per-category trends, so
    hard cases are never silently dropped from the denominator.
    """

    ASSIGN = "assign"
    ABSTAIN = "abstain"


class EvidenceSpan(BaseModel):
    """A character range in the complaint text supporting an enrichment.

    Offsets are half-open ``[start, end)`` over ``ComplaintEnvelope.text``.
    Carrying spans rather than copied text is what lets the render stage pull
    the quote from the store, so a quote cannot drift from its source.
    """

    model_config = ConfigDict(frozen=True)

    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.end <= self.start:
            msg = f"span end {self.end} must exceed start {self.start}"
            raise ValueError(msg)
        return self


class Enrichment(BaseModel):
    """Per-complaint structured record produced by the enrichment stage.

    ``confidence`` and ``novelty`` measure different things and are not
    interchangeable. Confidence is certainty *between known categories*;
    novelty is distance from the region of embedding space the known
    categories occupy. A genuinely new complaint type is frequently assigned
    to the nearest existing category *with high confidence* — detecting that
    needs the un-normalised measure. See the glossary in
    ``docs/design/01-problem-statement.md``.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    taxonomy_version: str

    #: Top-class probability, and the margin to the runner-up. Low margin
    #: means the record sits near a decision boundary.
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    margin: Annotated[float, Field(ge=0.0, le=1.0)]
    #: Category-normalised k-NN distance, percentile-thresholded so one
    #: threshold means the same thing for a broad category as a narrow one.
    novelty: Annotated[float, Field(ge=0.0, le=1.0)]

    #: -1 (most negative) to +1. Compared within channel, never across it.
    sentiment: Annotated[float, Field(ge=-1.0, le=1.0)]

    evidence_spans: tuple[EvidenceSpan, ...] = ()
    routing: RoutingDecision

    #: Set only for abstained records that clustered into a persistent theme.
    candidate_theme_id: str | None = None

    @model_validator(mode="after")
    def _check_theme_only_on_abstain(self) -> Self:
        if self.candidate_theme_id and self.routing is not RoutingDecision.ABSTAIN:
            msg = "candidate_theme_id is only valid on abstained records"
            raise ValueError(msg)
        return self


class ComplaintEnvelope(BaseModel):
    """The canonical complaint record. System of record for the demo.

    ``text`` is customer-supplied and adversarial-capable. It is data, never
    instruction, at every point it enters a prompt — including when returned
    by retrieval. Nothing in this class enforces that; the single choke point
    is ``agent.untrusted.render_untrusted``.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    channel: Channel
    received_date: date
    #: ISO week the complaint is counted in, e.g. ``2026-W31``.
    week: str
    product: str

    text: str
    status: ComplaintStatus
    enrichment: Enrichment

    #: True where the synthetic generator deliberately planted an injection
    #: payload or residual PII. Ground truth for the adversarial suite only —
    #: no production stage may read this, and no prompt ever sees it.
    is_adversarial_fixture: bool = False

    def span_text(self, span: EvidenceSpan) -> str:
        """Resolve a span to the text it covers.

        Raises rather than clipping: an out-of-range offset means a citation
        no longer matches its source, which is a provenance failure, not a
        formatting inconvenience.
        """
        if span.end > len(self.text):
            msg = (
                f"span {span.start}:{span.end} exceeds text length "
                f"{len(self.text)} for {self.complaint_id}"
            )
            raise ValueError(msg)
        return self.text[span.start : span.end]


class ResolutionNote(BaseModel):
    """Free-text record of the action taken on a closed complaint.

    These are the sole knowledge source for remediation recommendations. The
    system does not reason about root causes from first principles; it
    retrieves how comparable complaints were actually resolved.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    category: str
    outcome: Outcome
    #: Redress paid, in whole pounds. Zero where none was paid.
    redress_gbp: Annotated[int, Field(ge=0)]
    #: Calendar days from receipt to closure.
    days_to_close: Annotated[int, Field(ge=0)]
    text: str


class Precedent(BaseModel):
    """A closed complaint and what was done about it.

    The unit of remediation retrieval, and deliberately a pair. The complaint
    is what the search matched on — like against like, both being customer
    prose — and the note is what makes the match useful. Returning the note
    alone would leave the agent judging whether a precedent transfers without
    seeing the problem it was a response to.

    Carrying the complaint is also what makes the citations mean anything:
    precedent citations are offsets into complaint text, resolved against the
    store at render time, so the text the model was shown and the text those
    offsets index must be the same string.
    """

    model_config = ConfigDict(frozen=True)

    complaint: ComplaintEnvelope
    resolution: ResolutionNote

    @model_validator(mode="after")
    def _check_pairing(self) -> Self:
        if self.complaint.complaint_id != self.resolution.complaint_id:
            msg = (
                f"precedent pairs complaint {self.complaint.complaint_id!r} "
                f"with a note for {self.resolution.complaint_id!r}"
            )
            raise ValueError(msg)
        if self.complaint.status is not ComplaintStatus.CLOSED:
            msg = (
                f"precedent {self.complaint.complaint_id!r} is not closed; "
                f"an open complaint has no outcome to learn from"
            )
            raise ValueError(msg)
        return self
