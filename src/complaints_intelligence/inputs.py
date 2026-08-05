"""Schemas for everything entering the agent: complaints, resolution notes,
facts, and the metrics brief assembled from them.

Records here arrive *as if* they had already passed ingest, PII redaction,
injection screening, classification and enrichment — all out of scope.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------


class Channel(StrEnum):
    """Intake channel. Retained as a feature, not normalised away, because
    volume and sentiment both vary systematically by channel."""

    FOS_REFERRAL = "fos_referral"
    MOBILE_APP = "mobile_app"
    BRANCH = "branch"
    CALL_CENTRE = "call_centre"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Outcome(StrEnum):
    UPHELD = "upheld"
    PARTIALLY_UPHELD = "partially_upheld"
    NOT_UPHELD = "not_upheld"


class RoutingDecision(StrEnum):
    """Which track an enriched record was sent down.

    ``ABSTAIN`` is a deliberate refusal, not a failure: those records form the
    residual pool that theme discovery works over, and they still count in
    totals.
    """

    ASSIGN = "assign"
    ABSTAIN = "abstain"


class ComplaintEnvelope(BaseModel):
    """The canonical complaint record, and the system of record for the demo.

    ``text`` is customer-supplied and adversarial-capable; it is data, never
    instruction, and ``agent.untrusted`` is the single point where it may
    enter a prompt.
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

    #: Enrichment, produced upstream. ``category`` is the classifier's label;
    #: on an abstained record it is the nearest known category, not a verdict.
    category: str
    routing: RoutingDecision = RoutingDecision.ASSIGN
    #: -1 (most negative) to +1. Compared within channel, never pooled across.
    sentiment: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    #: Set only on abstained records that clustered into a persistent theme.
    candidate_theme_id: str | None = None

    #: True where the fixture deliberately plants an injection payload or
    #: residual PII. Ground truth for the tests only: no production path reads
    #: it, and no prompt ever sees it.
    is_adversarial_fixture: bool = False


class ResolutionNote(BaseModel):
    """Free-text record of the action taken on a closed complaint.

    These are the sole knowledge source for remediation: the system retrieves
    how comparable complaints were actually resolved rather than reasoning
    about root causes from first principles.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    category: str
    outcome: Outcome
    redress_gbp: Annotated[int, Field(ge=0)]
    days_to_close: Annotated[int, Field(ge=0)]
    text: str


class Precedent(BaseModel):
    """A closed complaint paired with what was done about it.

    Deliberately a pair: whether a precedent transfers is a question about the
    problem, and citations point into the complaint text, not the note.
    """

    model_config = ConfigDict(frozen=True)

    complaint: ComplaintEnvelope
    resolution: ResolutionNote


# ---------------------------------------------------------------------------
# Facts — the trust boundary
# ---------------------------------------------------------------------------

FactId = Annotated[str, Field(pattern=r"^f_\d{4}$")]


class FactUnit(StrEnum):
    """How a fact's value should be read and formatted.

    Carried on the fact rather than inferred at render time, so a proportion
    can never be printed as a count.
    """

    COMPLAINTS = "complaints"
    PROPORTION = "proportion"
    SENTIMENT_INDEX = "sentiment_index"
    COUNT = "count"


class Provenance(BaseModel):
    """The view and parameters a fact was derived from — enough to re-run the
    derivation eighteen months later and get the same value back."""

    model_config = ConfigDict(frozen=True)

    view: str
    params: dict[str, str]


class Fact(BaseModel):
    """A single precomputed figure with its provenance.

    Everything below the fact store is deterministic; everything above it is
    generative. Report claims reference fact IDs, never literal values.
    """

    model_config = ConfigDict(frozen=True)

    id: FactId
    label: str
    value: float
    unit: FactUnit
    provenance: Provenance
    category: str | None = None
    channel: str | None = None
    week: str | None = None

    def render(self) -> str:
        """Format the value for the report, so a figure is presented
        identically wherever it appears."""
        match self.unit:
            case FactUnit.PROPORTION:
                return f"{self.value * 100:.1f}%"
            case FactUnit.SENTIMENT_INDEX:
                return f"{self.value:+.2f}"
            case _:
                return f"{self.value:,.0f}"


# ---------------------------------------------------------------------------
# The metrics brief — the agent's entire view of the week
# ---------------------------------------------------------------------------


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class FlaggedCategory(BaseModel):
    """A category whose week-on-week movement cleared the reporting threshold.

    ``significant`` records whether the movement survived multiple-testing
    correction, so the agent can distinguish "moved" from "moved more than
    chance explains".
    """

    model_config = ConfigDict(frozen=True)

    category: str
    direction: Direction
    count_fact_id: FactId
    baseline_count_fact_id: FactId
    change_fact_id: FactId
    significant: bool
    #: Channel carrying most of the movement, where one dominates.
    concentrated_in_channel: str | None = None


class SentimentSignal(BaseModel):
    """A within-channel sentiment shift worth reporting.

    Never pooled across channels: a branch note and a call transcript have
    different registers, so a pooled mean moves when the channel mix moves.
    """

    model_config = ConfigDict(frozen=True)

    scope: str
    channel: str
    current_fact_id: FactId
    baseline_fact_id: FactId
    shift_fact_id: FactId
    direction: Direction


class CandidateTheme(BaseModel):
    """A persistent cluster in the residual pool, with a stable identity.

    Coherence, persistence, channel spread and duplicate ratio are the honest
    signals for adjudication — coherence alone is not, because near-identical
    text is trivially coherent.
    """

    model_config = ConfigDict(frozen=True)

    theme_id: Annotated[str, Field(pattern=r"^CT-\d{3}$")]
    #: Provisional label from clustering. Deliberately not authoritative — the
    #: agent adjudicates it and may reject the framing.
    provisional_label: str
    size_fact_id: FactId
    coherence: Annotated[float, Field(ge=0.0, le=1.0)]
    persistence_weeks: Annotated[int, Field(ge=1)]
    channel_concentration: Annotated[float, Field(ge=0.0, le=1.0)]
    duplicate_ratio: Annotated[float, Field(ge=0.0, le=1.0)]


class SkippedItem(BaseModel):
    """Something considered but not carried into the report. Recorded rather
    than dropped, because truncation that hides its own effects is not
    auditable."""

    model_config = ConfigDict(frozen=True)

    kind: str
    identifier: str
    reason: str


class MetricsBrief(BaseModel):
    """The compact object the metrics layer emits for one week. Every figure
    in it is a fact ID, never a literal value."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    week: str
    baseline_week: str
    taxonomy_version: str

    headline_fact_ids: tuple[FactId, ...]
    flagged_categories: tuple[FlaggedCategory, ...]
    sentiment_signals: tuple[SentimentSignal, ...]
    candidate_themes: tuple[CandidateTheme, ...]
    skipped: tuple[SkippedItem, ...] = ()
