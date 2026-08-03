"""The metrics brief: the agent's entire view of the week.

Built by ``metrics.build_brief`` from the run's facts using fixed, configured
thresholds, and truncated. This is deliberate — it bounds the run, makes weeks
comparable, and keeps the agent reproducible.

Anything the thresholds miss cannot appear in the report. That is why
thresholds are configuration with a stated minimum detectable effect, why
items considered but not carried are recorded rather than dropped, and why the
dashboard remains available for analysts who need to look further.

Every figure in the brief is a **fact ID**, never a literal value.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from complaints_intelligence.domain.fact import FactId


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class FlaggedCategory(BaseModel):
    """A category whose movement cleared the configured thresholds.

    ``significant`` records whether the velocity test survived Benjamini-
    Hochberg correction. With ~40 categories tested weekly, naive comparison
    produces false alarms continuously; carrying the corrected result lets the
    agent distinguish "moved" from "moved more than chance explains".
    """

    model_config = ConfigDict(frozen=True)

    category: str
    direction: Direction
    count_fact_id: FactId
    baseline_count_fact_id: FactId
    change_fact_id: FactId
    #: Benjamini-Hochberg adjusted p-value from the negative-binomial
    #: velocity test.
    adjusted_p_value: Annotated[float, Field(ge=0.0, le=1.0)]
    significant: bool
    #: Channel carrying most of the movement, where one dominates.
    concentrated_in_channel: str | None = None


class SentimentSignal(BaseModel):
    """A within-channel sentiment shift worth reporting.

    Sentiment is aggregated within channel and never pooled across channels:
    a branch note and a call transcript have systematically different
    registers, so a pooled mean moves when the channel mix moves.
    """

    model_config = ConfigDict(frozen=True)

    scope: str
    channel: str | None
    current_fact_id: FactId
    baseline_fact_id: FactId
    shift_fact_id: FactId
    direction: Direction


class CandidateTheme(BaseModel):
    """A persistent cluster in the residual pool, with a stable identity.

    Cluster linking across weeks is what gives ``CT-nnn`` a stable identity,
    so growth can be measured. Reported as narrative with evidence, never
    counted as a category — it has no comparable history, and adopting it is
    a separate, human-gated act.

    ``coherence`` and ``persistence_weeks`` are the honest signals for
    adjudication. A tight cluster that has appeared for several weeks is a
    theme; a tight cluster that appeared once in one channel is very often an
    ingest artefact.
    """

    model_config = ConfigDict(frozen=True)

    theme_id: Annotated[str, Field(pattern=r"^CT-\d{3}$")]
    #: Provisional label from clustering. Deliberately not authoritative —
    #: the agent adjudicates it and may reject the framing.
    provisional_label: str
    size_fact_id: FactId
    #: Mean intra-cluster cosine similarity. Higher is tighter.
    coherence: Annotated[float, Field(ge=0.0, le=1.0)]
    #: Consecutive weeks this identity has been seen.
    persistence_weeks: Annotated[int, Field(ge=1)]
    #: Share of members arriving through a single channel. A value near 1.0
    #: is a strong ingest-artefact signal.
    channel_concentration: Annotated[float, Field(ge=0.0, le=1.0)]
    #: Share of members that are near-duplicate text.
    duplicate_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    exemplar_complaint_ids: tuple[str, ...]


class HealthIndicators(BaseModel):
    """Pipeline health for the week.

    Abstention rate is a monitored signal, not a failure — but a sharp move in
    it changes how every other number should be read, so the agent sees it.
    """

    model_config = ConfigDict(frozen=True)

    total_complaints_fact_id: FactId
    abstention_rate_fact_id: FactId
    residual_share_fact_id: FactId
    quarantine_count_fact_id: FactId


class SkippedItem(BaseModel):
    """Something considered but not carried into the brief.

    Recorded rather than dropped. Truncation is a design choice, and a design
    choice that hides its own effects is not auditable.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    identifier: str
    reason: str


class MetricsBrief(BaseModel):
    """The compact object the metrics layer emits at the end of each run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    week: str
    baseline_week: str
    taxonomy_version: str

    headline_fact_ids: tuple[FactId, ...]
    top_drivers: tuple[FlaggedCategory, ...]
    flagged_categories: tuple[FlaggedCategory, ...]
    sentiment_signals: tuple[SentimentSignal, ...]
    candidate_themes: tuple[CandidateTheme, ...]
    health: HealthIndicators
    skipped: tuple[SkippedItem, ...] = ()
