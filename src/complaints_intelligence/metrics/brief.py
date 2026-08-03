"""Building the metrics brief.

The brief is the agent's entire view of the week. Everything it can report on
must appear here; anything the thresholds miss cannot reach the report.

That is a deliberate constraint, and it is the reason for two properties of
this module. Thresholds are configuration with a stated minimum detectable
effect rather than heuristics buried at call sites. And items considered but
not carried are recorded in ``skipped`` rather than dropped, so the truncation
is visible to anyone auditing why something is absent.
"""

from __future__ import annotations

from complaints_intelligence.config import BriefThresholds
from complaints_intelligence.domain.brief import (
    CandidateTheme,
    Direction,
    FlaggedCategory,
    HealthIndicators,
    MetricsBrief,
    SentimentSignal,
    SkippedItem,
)
from complaints_intelligence.logging import get_logger
from complaints_intelligence.metrics.facts import FactSet, _make_key
from complaints_intelligence.metrics.statistics import (
    VelocityTest,
    run_mean_shift_tests,
)
from complaints_intelligence.store.duckdb_store import DuckDBStore

log = get_logger(__name__)

#: Channel share above which a movement is described as concentrated.
_CONCENTRATION_THRESHOLD = 0.55

#: Number of exemplar complaint IDs carried per candidate theme. Enough for
#: the agent to characterise the theme, few enough to keep the brief compact.
_THEME_EXEMPLARS = 5


def _direction(change: float, flat_band: float) -> Direction:
    if change > flat_band:
        return Direction.UP
    if change < -flat_band:
        return Direction.DOWN
    return Direction.FLAT


def _dominant_channel(
    store: DuckDBStore, category: str, week: str
) -> tuple[str, float] | None:
    """Channel carrying the largest share of a category, with that share."""
    rows = store.query_view(
        "v_weekly_category_channel_counts", {"week": week, "category": category}
    )
    total = sum(int(r["complaint_count"]) for r in rows)
    if not total:
        return None
    top = max(rows, key=lambda r: (int(r["complaint_count"]), str(r["channel"])))
    return str(top["channel"]), int(top["complaint_count"]) / total


def _build_flagged(
    store: DuckDBStore,
    facts: FactSet,
    tests: list[VelocityTest],
    *,
    week: str,
    baseline_week: str,
    thresholds: BriefThresholds,
) -> tuple[list[FlaggedCategory], list[SkippedItem]]:
    """Apply the thresholds to the velocity tests.

    A category is flagged when it moved by more than the configured
    proportion *and* had enough baseline volume for that proportion to mean
    anything. Significance is carried alongside rather than used as the gate:
    a large movement that fails correction is still worth the agent seeing, so
    it can say the movement was tested and did not hold up. Suppressing it
    entirely would leave the reader unable to tell "did not happen" from
    "was never looked at".
    """
    flagged: list[FlaggedCategory] = []
    skipped: list[SkippedItem] = []

    for test in tests:
        if test.baseline < thresholds.min_baseline_count:
            skipped.append(
                SkippedItem(
                    kind="category",
                    identifier=test.category,
                    reason=(
                        f"baseline {test.baseline} below minimum "
                        f"{thresholds.min_baseline_count}; proportional change "
                        f"not meaningful"
                    ),
                )
            )
            continue

        if abs(test.change) < thresholds.volume_change_flag:
            continue

        dominant = _dominant_channel(store, test.category, week)
        concentrated = (
            dominant[0]
            if dominant and dominant[1] >= _CONCENTRATION_THRESHOLD
            else None
        )

        flagged.append(
            FlaggedCategory(
                category=test.category,
                direction=_direction(test.change, thresholds.volume_change_flag),
                count_fact_id=facts.lookup(
                    "v_weekly_category_counts",
                    _make_key(category=test.category, week=week),
                ),
                baseline_count_fact_id=facts.lookup(
                    "v_weekly_category_counts",
                    _make_key(category=test.category, week=baseline_week),
                ),
                change_fact_id=facts.lookup(
                    "v_weekly_category_counts",
                    _make_key(category=test.category, measure="wow_change", week=week),
                ),
                adjusted_p_value=test.adjusted_p_value,
                significant=test.significant,
                concentrated_in_channel=concentrated,
            )
        )

    # Rank by absolute movement, then by category for a stable tie-break.
    flagged.sort(key=lambda f: (-abs(_change_of(f, tests)), f.category))

    if len(flagged) > thresholds.max_flagged_categories:
        for dropped in flagged[thresholds.max_flagged_categories :]:
            skipped.append(
                SkippedItem(
                    kind="category",
                    identifier=dropped.category,
                    reason=(
                        f"ranked below top {thresholds.max_flagged_categories} "
                        f"by absolute movement"
                    ),
                )
            )
        flagged = flagged[: thresholds.max_flagged_categories]

    return flagged, skipped


def _change_of(flagged: FlaggedCategory, tests: list[VelocityTest]) -> float:
    for test in tests:
        if test.category == flagged.category:
            return test.change
    return 0.0


def _build_sentiment(
    store: DuckDBStore,
    facts: FactSet,
    *,
    week: str,
    baseline_week: str,
    thresholds: BriefThresholds,
) -> list[SentimentSignal]:
    """Find within-channel sentiment shifts worth reporting.

    Compared strictly within channel and category. Pooling across channels
    would make the index move whenever the channel mix moved, which is a
    change in who complained, not in how they felt.
    """
    current = {
        (str(r["channel"]), str(r["category"])): r
        for r in store.query_view("v_sentiment_by_channel_week", {"week": week})
    }
    baseline = {
        (str(r["channel"]), str(r["category"])): r
        for r in store.query_view(
            "v_sentiment_by_channel_week", {"week": baseline_week}
        )
    }

    # Test every cell, then require both statistical significance and a shift
    # large enough to be worth a reader's attention. Significance alone would
    # surface trivial moves in large cells; a threshold alone would surface
    # noise in small ones. Both gates are needed, and for different reasons.
    cells: dict[tuple[str, str], tuple[float, float, int, float, float, int]] = {}
    for key in sorted(set(current) & set(baseline)):
        channel, category = key
        cells[(category, channel)] = (
            float(baseline[key]["mean_sentiment"]),
            float(baseline[key]["stddev_sentiment"]),
            int(baseline[key]["complaint_count"]),
            float(current[key]["mean_sentiment"]),
            float(current[key]["stddev_sentiment"]),
            int(current[key]["complaint_count"]),
        )

    signals: list[SentimentSignal] = []
    for test in run_mean_shift_tests(cells, alpha=thresholds.fdr_alpha):
        if not test.significant:
            continue
        if abs(test.shift) < thresholds.sentiment_shift_flag:
            continue

        signals.append(
            SentimentSignal(
                scope=test.scope,
                channel=test.channel,
                current_fact_id=facts.lookup(
                    "v_sentiment_by_channel_week",
                    _make_key(category=test.scope, channel=test.channel, week=week),
                ),
                baseline_fact_id=facts.lookup(
                    "v_sentiment_by_channel_week",
                    _make_key(
                        category=test.scope, channel=test.channel, week=baseline_week
                    ),
                ),
                shift_fact_id=facts.lookup(
                    "v_sentiment_by_channel_week",
                    _make_key(
                        category=test.scope,
                        channel=test.channel,
                        measure="sentiment_shift",
                        week=week,
                    ),
                ),
                direction=Direction.DOWN if test.shift < 0 else Direction.UP,
            )
        )

    signals.sort(key=lambda s: (s.scope, s.channel or ""))
    return signals


def _build_themes(
    store: DuckDBStore,
    facts: FactSet,
    *,
    week: str,
    thresholds: BriefThresholds,
    persistence: dict[str, int],
) -> tuple[list[CandidateTheme], list[SkippedItem]]:
    """Carry candidate themes into the brief, largest first.

    Coherence, channel concentration and duplicate ratio are all *measured*
    from the data rather than asserted. They are the signals that let the
    agent tell a genuine emerging theme from a batch of duplicated CRM notes,
    and a measure that was declared rather than computed would tell it
    nothing.
    """
    rows = store.query_view("v_candidate_themes", {"week": week})
    rows.sort(key=lambda r: (-int(r["member_count"]), str(r["theme_id"])))

    themes: list[CandidateTheme] = []
    skipped: list[SkippedItem] = []

    for position, row in enumerate(rows):
        theme_id = str(row["theme_id"])
        if position >= thresholds.max_candidate_themes:
            skipped.append(
                SkippedItem(
                    kind="candidate_theme",
                    identifier=theme_id,
                    reason=(
                        f"ranked below top {thresholds.max_candidate_themes} by size"
                    ),
                )
            )
            continue

        members = store.theme_members(theme_id, week)
        themes.append(
            CandidateTheme(
                theme_id=theme_id,
                provisional_label=_provisional_label(members),
                size_fact_id=facts.lookup(
                    "v_candidate_themes", _make_key(theme_id=theme_id, week=week)
                ),
                coherence=_coherence(store, theme_id, week),
                persistence_weeks=persistence.get(theme_id, 1),
                channel_concentration=float(row["channel_concentration"]),
                duplicate_ratio=float(row["duplicate_ratio"]),
                exemplar_complaint_ids=tuple(
                    c.complaint_id for c in members[:_THEME_EXEMPLARS]
                ),
            )
        )

    return themes, skipped


def _provisional_label(members: tuple[object, ...]) -> str:
    """A neutral placeholder label for a cluster.

    Deliberately uninformative. Clustering produces a group, not a
    description of it; naming the group is a judgement the agent makes from
    the evidence, and handing it a confident label here would be handing it
    the answer.
    """
    return f"unlabelled cluster of {len(members)} complaints"


def _coherence(store: DuckDBStore, theme_id: str, week: str) -> float:
    """Mean pairwise similarity within a cluster, measured from vectors."""
    return store.theme_coherence(theme_id, week)


def build_brief(
    store: DuckDBStore,
    facts: FactSet,
    tests: list[VelocityTest],
    *,
    run_id: str,
    week: str,
    baseline_week: str,
    taxonomy_version: str,
    thresholds: BriefThresholds,
    persistence: dict[str, int] | None = None,
) -> MetricsBrief:
    """Assemble the brief from the run's facts.

    ``persistence`` maps theme ID to consecutive weeks seen, supplied by the
    cluster-linking service. Only two weeks are generated in this demo, so
    values above two come from the signal specification; see the note in
    ``synth.generator``.
    """
    flagged, skipped = _build_flagged(
        store,
        facts,
        tests,
        week=week,
        baseline_week=baseline_week,
        thresholds=thresholds,
    )
    sentiment = _build_sentiment(
        store, facts, week=week, baseline_week=baseline_week, thresholds=thresholds
    )
    themes, theme_skips = _build_themes(
        store,
        facts,
        week=week,
        thresholds=thresholds,
        persistence=persistence or {},
    )

    health = HealthIndicators(
        total_complaints_fact_id=facts.lookup(
            "v_health_indicators", _make_key(measure="total_complaints", week=week)
        ),
        abstention_rate_fact_id=facts.lookup(
            "v_health_indicators", _make_key(measure="abstention_rate", week=week)
        ),
        residual_share_fact_id=facts.lookup(
            "v_health_indicators", _make_key(measure="residual_share", week=week)
        ),
        quarantine_count_fact_id=facts.lookup(
            "v_health_indicators", _make_key(measure="quarantine_count", week=week)
        ),
    )

    # Top drivers are the five largest categories by current volume, which is
    # a different question from which moved most. The report needs both: what
    # is biggest, and what changed.
    top_drivers = tuple(
        f
        for f in sorted(
            flagged,
            key=lambda f: (-_current_count(facts, f), f.category),
        )[:5]
    )

    brief = MetricsBrief(
        run_id=run_id,
        week=week,
        baseline_week=baseline_week,
        taxonomy_version=taxonomy_version,
        headline_fact_ids=(
            health.total_complaints_fact_id,
            health.abstention_rate_fact_id,
        ),
        top_drivers=top_drivers,
        flagged_categories=tuple(flagged),
        sentiment_signals=tuple(sentiment),
        candidate_themes=tuple(themes),
        health=health,
        skipped=tuple(skipped + theme_skips),
    )

    log.info(
        "brief_built",
        run_id=run_id,
        flagged=len(brief.flagged_categories),
        sentiment_signals=len(brief.sentiment_signals),
        candidate_themes=len(brief.candidate_themes),
        skipped=len(brief.skipped),
    )
    return brief


def _current_count(facts: FactSet, flagged: FlaggedCategory) -> float:
    for fact in facts:
        if fact.id == flagged.count_fact_id:
            return fact.value
    return 0.0
