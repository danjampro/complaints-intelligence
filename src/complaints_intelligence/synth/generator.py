"""Seeded synthetic complaint generation.

Produces two weeks of complaints — a baseline and a reporting week — with the
signals in ``synth.signals`` planted in them, plus resolution notes on the
closed subset.

Generation is deterministic given a seed (invariant 6). Every random draw comes
from a single ``numpy.random.Generator``; nothing reads the clock, the
environment, or global random state.

Records are produced *as if* they had already passed ingest, redaction,
injection screening, classification and enrichment. Those stages are out of
scope; the enrichment fields here are synthesised to be internally consistent
rather than computed by a real classifier.

One honest limitation: ``persistence_weeks`` on a candidate theme describes how
many consecutive weeks cluster linking has seen that identity. Only two weeks
are generated here, so values above two are carried from the signal
specification as given, standing in for the linking service's history.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from numpy.random import Generator
from pydantic import BaseModel, ConfigDict

from complaints_intelligence.config import TAXONOMY_VERSION, SynthConfig
from complaints_intelligence.domain.complaint import (
    Channel,
    ComplaintEnvelope,
    ComplaintStatus,
    Enrichment,
    EvidenceSpan,
    Outcome,
    ResolutionNote,
    RoutingDecision,
)
from complaints_intelligence.logging import get_logger
from complaints_intelligence.synth import signals as sig
from complaints_intelligence.synth.taxonomy import CATEGORIES, get_node
from complaints_intelligence.synth.templates import (
    CATEGORY_PHRASES,
    CHANNEL_CLOSERS,
    CHANNEL_OPENERS,
    RESOLUTION_ACTIONS,
    THEME_PHRASES,
    channel_register,
)

log = get_logger(__name__)

#: Baseline volume for a category with no planted signal.
_BASE_CATEGORY_VOLUME = 38

#: Scattered abstentions that do not belong to any candidate theme. Real
#: residual pools are mostly this: genuinely ambiguous one-offs.
_SCATTERED_ABSTENTIONS = 30

#: Channel mix for a category with no concentration.
_BASE_CHANNEL_WEIGHTS: dict[Channel, float] = {
    Channel.MOBILE_APP: 0.40,
    Channel.CALL_CENTRE: 0.30,
    Channel.BRANCH: 0.20,
    Channel.FOS_REFERRAL: 0.10,
}

#: Share taken by the dominant channel where a signal is concentrated.
_CONCENTRATION_SHARE = 0.70

#: Mean sentiment by channel. Registers differ systematically, which is why
#: sentiment is aggregated within channel and never pooled across it.
_CHANNEL_SENTIMENT: dict[Channel, float] = {
    Channel.FOS_REFERRAL: -0.62,
    Channel.MOBILE_APP: -0.54,
    Channel.CALL_CENTRE: -0.48,
    Channel.BRANCH: -0.38,
}

#: Category adjustment on top of the channel mean.
_CATEGORY_SENTIMENT: dict[str, float] = {
    "vulnerable_customer_support": -0.20,
    "mortgage_arrears_support": -0.18,
    "complaint_handling_delay": -0.15,
    "card_fraud_handling": -0.12,
    "payments_failed": -0.06,
    "statement_errors": 0.10,
    "savings_rate_change": 0.08,
    "branch_closure": 0.04,
}

_OUTCOMES: tuple[Outcome, ...] = (
    Outcome.UPHELD,
    Outcome.PARTIALLY_UPHELD,
    Outcome.NOT_UPHELD,
)
_OUTCOME_WEIGHTS = (0.45, 0.30, 0.25)

#: Closed share by week. Recent complaints are still open; older ones are not.
_CLOSED_FRACTION_BY_AGE = (0.82, 0.38)


class Dataset(BaseModel):
    """The generated corpus."""

    model_config = ConfigDict(frozen=True)

    complaints: tuple[ComplaintEnvelope, ...]
    resolutions: tuple[ResolutionNote, ...]

    def for_week(self, week: str) -> tuple[ComplaintEnvelope, ...]:
        return tuple(c for c in self.complaints if c.week == week)


def _week_start(week: str) -> date:
    """Monday of an ISO week string such as ``2026-W31``."""
    year_part, week_part = week.split("-W")
    return date.fromisocalendar(int(year_part), int(week_part), 1)


def _choose_channel(rng: Generator, concentrated_in: Channel | None) -> Channel:
    """Draw a channel, optionally weighted towards a dominant one."""
    channels = list(_BASE_CHANNEL_WEIGHTS)
    if concentrated_in is None:
        weights = [_BASE_CHANNEL_WEIGHTS[c] for c in channels]
    else:
        remainder = 1.0 - _CONCENTRATION_SHARE
        others = [c for c in channels if c is not concentrated_in]
        other_total = sum(_BASE_CHANNEL_WEIGHTS[c] for c in others)
        weights = [
            _CONCENTRATION_SHARE
            if c is concentrated_in
            else remainder * _BASE_CHANNEL_WEIGHTS[c] / other_total
            for c in channels
        ]
    idx = int(rng.choice(len(channels), p=np.asarray(weights, dtype=float)))
    return channels[idx]


def _compose_text(
    rng: Generator,
    channel: Channel,
    phrases: dict[str, tuple[str, ...]],
) -> tuple[str, EvidenceSpan]:
    """Build one complaint body and the span covering its grievance clause.

    The span is returned rather than recomputed by searching the text, so an
    evidence offset is correct by construction. A citation that has to find
    its own quote is a citation that can drift.
    """
    opener = str(rng.choice(CHANNEL_OPENERS[channel]))
    grievance = str(rng.choice(phrases["grievance"]))
    detail = str(rng.choice(phrases["detail"]))
    impact = str(rng.choice(phrases["impact"]))
    closer = str(rng.choice(CHANNEL_CLOSERS[channel]))

    prefix = f"{opener} " if opener else ""
    body = f"{prefix}{grievance}. {detail}, and {impact}."
    text = f"{body} {closer}".strip() if closer else body
    text = channel_register(channel, text)

    # Locate the grievance after register transformation, which can change
    # lengths. Falling back to the whole body keeps offsets valid rather than
    # silently emitting a span that no longer covers what it claims to.
    transformed = channel_register(channel, grievance)
    start = text.find(transformed)
    if start == -1:
        start, end = 0, min(len(text), len(body))
    else:
        end = start + len(transformed)
    return text, EvidenceSpan(start=start, end=end)


def _sentiment(rng: Generator, channel: Channel, category: str, shift: float) -> float:
    """Draw a sentiment score for one complaint."""
    mean = _CHANNEL_SENTIMENT[channel] + _CATEGORY_SENTIMENT.get(category, 0.0) + shift
    return float(np.clip(rng.normal(mean, 0.18), -1.0, 1.0))


def _assigned_enrichment(
    rng: Generator, category: str, sentiment: float, span: EvidenceSpan
) -> Enrichment:
    """Enrichment for a record the classifier was willing to assign."""
    confidence = float(np.clip(rng.beta(9.0, 2.0), 0.0, 1.0))
    return Enrichment(
        category=category,
        taxonomy_version=TAXONOMY_VERSION,
        confidence=confidence,
        margin=float(np.clip(rng.beta(5.0, 3.0) * confidence, 0.0, 1.0)),
        novelty=float(np.clip(rng.beta(2.0, 8.0), 0.0, 1.0)),
        sentiment=sentiment,
        vulnerability_flag=bool(
            rng.random() < (0.55 if category == "vulnerable_customer_support" else 0.06)
        ),
        detriment_flag=bool(rng.random() < 0.35),
        evidence_spans=(span,),
        routing=RoutingDecision.ASSIGN,
    )


def _abstained_enrichment(
    rng: Generator,
    nearest_category: str,
    sentiment: float,
    span: EvidenceSpan,
    theme_id: str | None,
    *,
    confidently_wrong: bool,
) -> Enrichment:
    """Enrichment for an abstained record.

    ``confidently_wrong`` produces the high-confidence, high-novelty quadrant:
    softmax is normalised across known classes and has no "none of these"
    output, so a genuinely new complaint type is frequently assigned to the
    nearest existing category *with high confidence*. Those records are the
    reason novelty is measured separately, and they are where new categories
    hide.
    """
    if confidently_wrong:
        confidence = float(np.clip(rng.beta(8.0, 2.0), 0.0, 1.0))
        margin = float(np.clip(rng.beta(4.0, 3.0) * confidence, 0.0, 1.0))
    else:
        confidence = float(np.clip(rng.beta(2.5, 4.0), 0.0, 1.0))
        margin = float(np.clip(rng.beta(1.5, 6.0) * confidence, 0.0, 1.0))

    return Enrichment(
        category=nearest_category,
        taxonomy_version=TAXONOMY_VERSION,
        confidence=confidence,
        margin=margin,
        novelty=float(np.clip(rng.beta(8.0, 2.0), 0.0, 1.0)),
        sentiment=sentiment,
        vulnerability_flag=bool(rng.random() < 0.08),
        detriment_flag=bool(rng.random() < 0.30),
        evidence_spans=(span,),
        routing=RoutingDecision.ABSTAIN,
        candidate_theme_id=theme_id,
    )


class _IdFactory:
    """Sequential, week-scoped complaint identifiers.

    Readable on sight (``CMP-2026W31-0042``) because a reviewer will be
    tracing these by eye from the report back into the Parquet.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next_id(self, week: str) -> str:
        n = self._counters.get(week, 0) + 1
        self._counters[week] = n
        return f"CMP-{week.replace('-', '')}-{n:04d}"


def _category_volume(category: str, week: str, config: SynthConfig) -> int:
    """Target count for a category in a week, honouring planted signals."""
    for signal in sig.VOLUME_SIGNALS:
        if signal.category == category:
            return (
                signal.reporting_count
                if week == config.reporting_week
                else signal.baseline_count
            )
    return _BASE_CATEGORY_VOLUME


def _sentiment_shift(category: str, week: str, config: SynthConfig) -> float:
    """Sentiment adjustment applied to a category in the reporting week."""
    if week != config.reporting_week:
        return 0.0
    for signal in sig.VOLUME_SIGNALS:
        if signal.category == category:
            return signal.sentiment_delta
    return 0.0


def _concentration(category: str, week: str, config: SynthConfig) -> Channel | None:
    """Dominant channel for a category, only in the week the signal fires."""
    if week != config.reporting_week:
        return None
    for signal in sig.VOLUME_SIGNALS:
        if signal.category == category:
            return signal.concentrated_in
    return None


def _theme_size(theme: sig.ThemeSignal, week: str, config: SynthConfig) -> int:
    """How many members of a theme appear in a given week.

    A theme seen for more than one week is planted in the baseline too, at
    reduced size, so its growth is visible in the data rather than merely
    asserted by its metadata.
    """
    if week == config.reporting_week:
        return theme.size
    return int(theme.size * 0.55) if theme.persistence_weeks > 1 else 0


def _generate_week(
    rng: Generator,
    week: str,
    week_index: int,
    config: SynthConfig,
    ids: _IdFactory,
) -> list[ComplaintEnvelope]:
    """Generate every complaint for one week."""
    start = _week_start(week)
    closed_fraction = _CLOSED_FRACTION_BY_AGE[week_index]
    out: list[ComplaintEnvelope] = []

    # --- Assigned records, by category -----------------------------------
    for category in CATEGORIES:
        volume = _category_volume(category, week, config)
        concentrated = _concentration(category, week, config)
        shift = _sentiment_shift(category, week, config)
        product = get_node(category).product

        for _ in range(volume):
            channel = _choose_channel(rng, concentrated)
            text, span = _compose_text(rng, channel, CATEGORY_PHRASES[category])
            sentiment = _sentiment(rng, channel, category, shift)
            out.append(
                ComplaintEnvelope(
                    complaint_id=ids.next_id(week),
                    channel=channel,
                    received_date=start + timedelta(days=int(rng.integers(0, 7))),
                    week=week,
                    product=product,
                    text=text,
                    status=(
                        ComplaintStatus.CLOSED
                        if rng.random() < closed_fraction
                        else ComplaintStatus.OPEN
                    ),
                    enrichment=_assigned_enrichment(rng, category, sentiment, span),
                )
            )

    # --- Candidate themes in the residual pool ---------------------------
    for theme in sig.THEME_SIGNALS:
        size = _theme_size(theme, week, config)
        # The nearest known category is what a closed-set classifier would
        # have forced this into. Recording it is what makes the abstention
        # legible: "we declined to call this X" is more useful than silence.
        nearest = _nearest_category_for_theme(theme.theme_id)
        for member in range(size):
            channel = theme.channels[member % len(theme.channels)]
            text, span = _compose_text(rng, channel, THEME_PHRASES[theme.theme_id])
            sentiment = _sentiment(rng, channel, nearest, 0.0)
            out.append(
                ComplaintEnvelope(
                    complaint_id=ids.next_id(week),
                    channel=channel,
                    received_date=start + timedelta(days=int(rng.integers(0, 7))),
                    week=week,
                    product=get_node(nearest).product,
                    text=text,
                    status=(
                        ComplaintStatus.CLOSED
                        if rng.random() < closed_fraction * 0.4
                        else ComplaintStatus.OPEN
                    ),
                    enrichment=_abstained_enrichment(
                        rng,
                        nearest,
                        sentiment,
                        span,
                        theme.theme_id,
                        # A coherent, genuinely novel theme reads as
                        # confidently wrong; a loose one reads as ambiguous.
                        confidently_wrong=theme.coherence > 0.6,
                    ),
                )
            )

    # --- Scattered abstentions -------------------------------------------
    for _ in range(_SCATTERED_ABSTENTIONS):
        category = str(rng.choice(np.asarray(CATEGORIES)))
        channel = _choose_channel(rng, None)
        text, span = _compose_text(rng, channel, CATEGORY_PHRASES[category])
        sentiment = _sentiment(rng, channel, category, 0.0)
        out.append(
            ComplaintEnvelope(
                complaint_id=ids.next_id(week),
                channel=channel,
                received_date=start + timedelta(days=int(rng.integers(0, 7))),
                week=week,
                product=get_node(category).product,
                text=text,
                status=(
                    ComplaintStatus.CLOSED
                    if rng.random() < closed_fraction
                    else ComplaintStatus.OPEN
                ),
                enrichment=_abstained_enrichment(
                    rng, category, sentiment, span, None, confidently_wrong=False
                ),
            )
        )

    return out


def _nearest_category_for_theme(theme_id: str) -> str:
    """The known category a closed-set classifier would force a theme into."""
    return {
        "CT-007": "payments_failed",
        "CT-012": "branch_closure",
        "CT-019": "complaint_handling_delay",
    }[theme_id]


def _plant_adversarial(
    rng: Generator,
    complaints: list[ComplaintEnvelope],
    config: SynthConfig,
) -> int:
    """Splice injection payloads and residual PII into existing complaints.

    Planted in the data rather than screened out of it. Filtering these at
    generation would test nothing: the claim being demonstrated is that
    untrusted text is safe to *retrieve*, not that it never exists. They must
    therefore reach the retrieval layer intact.

    Returns the number of complaints modified.
    """
    planted = 0
    for signal in sig.ADVERSARIAL_SIGNALS:
        matches = [
            i
            for i, c in enumerate(complaints)
            if c.week == config.reporting_week
            and c.channel is signal.channel
            and c.enrichment.category == signal.category
            and not c.is_adversarial_fixture
        ]
        if not matches:
            log.warning(
                "adversarial_signal_unplaced",
                kind=signal.kind,
                category=signal.category,
                channel=signal.channel.value,
            )
            continue

        idx = matches[int(rng.integers(0, len(matches)))]
        original = complaints[idx]
        text = f"{original.text} {signal.payload}"
        # Spans were computed against the original prefix, so appending
        # leaves every existing offset valid.
        complaints[idx] = original.model_copy(
            update={"text": text, "is_adversarial_fixture": True}
        )
        planted += 1
    return planted


def _generate_resolutions(
    rng: Generator, complaints: list[ComplaintEnvelope]
) -> list[ResolutionNote]:
    """Write a resolution note for every closed complaint.

    These are the sole knowledge source for remediation recommendations, so
    the action vocabulary is concrete and per-category: the report should be
    able to say what was actually done, not offer generic advice.
    """
    notes: list[ResolutionNote] = []
    for complaint in complaints:
        if complaint.status is not ComplaintStatus.CLOSED:
            continue
        category = complaint.enrichment.category
        actions = RESOLUTION_ACTIONS.get(category)
        if not actions:
            continue

        outcome = _OUTCOMES[
            int(rng.choice(len(_OUTCOMES), p=np.asarray(_OUTCOME_WEIGHTS)))
        ]
        match outcome:
            case Outcome.UPHELD:
                redress = int(rng.integers(50, 500))
            case Outcome.PARTIALLY_UPHELD:
                redress = int(rng.integers(25, 200))
            case _:
                redress = 0

        action = str(rng.choice(np.asarray(actions)))
        notes.append(
            ResolutionNote(
                complaint_id=complaint.complaint_id,
                category=category,
                outcome=outcome,
                redress_gbp=redress,
                days_to_close=int(rng.integers(4, 46)),
                text=f"Outcome: {outcome.value.replace('_', ' ')}. {action}",
            )
        )
    return notes


def generate(config: SynthConfig | None = None) -> Dataset:
    """Generate the full synthetic corpus.

    Deterministic for a given ``config.seed``.
    """
    cfg = config or SynthConfig()
    rng = np.random.default_rng(cfg.seed)
    ids = _IdFactory()

    complaints: list[ComplaintEnvelope] = []
    for week_index, week in enumerate((cfg.baseline_week, cfg.reporting_week)):
        complaints.extend(_generate_week(rng, week, week_index, cfg, ids))

    planted = _plant_adversarial(rng, complaints, cfg)
    resolutions = _generate_resolutions(rng, complaints)

    log.info(
        "synthetic_corpus_generated",
        seed=cfg.seed,
        complaints=len(complaints),
        resolutions=len(resolutions),
        adversarial_planted=planted,
        baseline_week=cfg.baseline_week,
        reporting_week=cfg.reporting_week,
    )
    return Dataset(complaints=tuple(complaints), resolutions=tuple(resolutions))
