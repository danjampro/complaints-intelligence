"""Assembling the metrics brief — the agent's entire view of the week.

The metrics layer's verdicts (what moved, what survived multiple-testing
correction) are computed upstream and committed in ``fixtures/brief.json``.
What is measurable from the complaints themselves is measured here.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.config import TAXONOMY_VERSION
from complaints_intelligence.inputs import (
    CandidateTheme,
    Direction,
    FlaggedCategory,
    MetricsBrief,
    SentimentSignal,
)
from complaints_intelligence.store import Store


def build_brief(store: Store, spec: dict[str, Any]) -> MetricsBrief:
    """Build the brief, ranking flagged categories most significant first.

    Ranking here rather than in the agent is deliberate: which movements matter
    is a statistical question the metrics layer has already answered, and the
    order decides what the investigation budget can reach.
    """
    facts = {fact.id: fact for fact in store.all_facts()}

    def value_of(fact_id: str) -> float:
        _require(facts, fact_id)
        return facts[fact_id].value

    flagged = [
        FlaggedCategory(
            category=row["category"],
            direction=Direction(row["direction"]),
            count_fact_id=_require(facts, row["count_fact_id"]),
            baseline_count_fact_id=_require(facts, row["baseline_count_fact_id"]),
            change_fact_id=_require(facts, row["change_fact_id"]),
            significant=row["significant"],
            concentrated_in_channel=row["concentrated_in_channel"],
        )
        for row in spec["categories"]
    ]
    # Significant first, then by the size of the movement. A movement that
    # failed its test is still carried — "tested and not significant" has to
    # read differently from "never looked at" — but it ranks below every
    # movement that held up, so it is the first thing the budget drops.
    flagged.sort(
        key=lambda f: (not f.significant, -abs(value_of(f.change_fact_id)), f.category)
    )

    sentiment = tuple(
        SentimentSignal(
            scope=row["scope"],
            channel=row["channel"],
            current_fact_id=_require(facts, row["current_fact_id"]),
            baseline_fact_id=_require(facts, row["baseline_fact_id"]),
            shift_fact_id=_require(facts, row["shift_fact_id"]),
            direction=Direction(row["direction"]),
        )
        for row in spec["sentiment"]
    )

    themes = tuple(
        CandidateTheme(
            theme_id=row["theme_id"],
            provisional_label=row["provisional_label"],
            size_fact_id=_require(facts, row["size_fact_id"]),
            # Measured, not declared. A declared coherence would carry no
            # information, and the measured values are the point: duplicated
            # text scores far tighter than a genuine emerging theme.
            coherence=store.theme_coherence(row["theme_id"]),
            duplicate_ratio=store.theme_duplicate_ratio(row["theme_id"]),
            channel_concentration=store.theme_channel_concentration(row["theme_id"]),
            # Supplied by the cluster-linking service, which is upstream.
            persistence_weeks=row["persistence_weeks"],
        )
        for row in spec["themes"]
    )

    return MetricsBrief(
        run_id=spec["run_id"],
        week=spec["week"],
        baseline_week=spec["baseline_week"],
        taxonomy_version=TAXONOMY_VERSION,
        headline_fact_ids=tuple(_require(facts, f) for f in spec["headline_fact_ids"]),
        flagged_categories=tuple(flagged),
        sentiment_signals=sentiment,
        candidate_themes=themes,
    )


def _require(facts: dict[str, Any], fact_id: str) -> str:
    """Fail loudly if the brief references a figure the fact store lacks.

    Caught here rather than at render time, because a brief pointing at a
    missing fact means the metrics layer and the fact store have diverged.
    """
    if fact_id not in facts:
        msg = f"the brief references {fact_id!r}, which the fact store does not hold"
        raise KeyError(msg)
    return fact_id
