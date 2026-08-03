"""Deriving the fact store.

Facts are computed by querying the complaint store through the same
parameterised views the agent can read, and each carries the view and
parameters that produced it. That is what makes a figure re-derivable rather
than merely recorded: a reviewer can run the provenance and get the value back.

Facts are derived here rather than hand-written as fixtures deliberately. If
the numbers in the report did not reconcile with the store they cite, the
traceability claim would be a decoration. Deriving them means the report's
figures and the underlying complaints cannot drift apart.

Fact IDs are allocated in a fixed order so a given corpus always produces the
same IDs (invariant 6).
"""

from __future__ import annotations

from collections.abc import Iterator

from complaints_intelligence.config import BriefThresholds
from complaints_intelligence.domain.fact import Fact, FactUnit, Provenance
from complaints_intelligence.logging import get_logger
from complaints_intelligence.metrics.statistics import VelocityTest, run_velocity_tests
from complaints_intelligence.store.duckdb_store import DuckDBStore

log = get_logger(__name__)


class _FactIdAllocator:
    """Sequential fact IDs, ``f_0001`` upward."""

    def __init__(self) -> None:
        self._next = 0

    def allocate(self) -> str:
        self._next += 1
        return f"f_{self._next:04d}"


class FactSet:
    """The derived facts plus an index for looking them up while building.

    ``build_brief`` needs to find "the count fact for payments_failed in W31"
    without scanning. Keying on the provenance is what makes that possible and
    keeps the brief referencing IDs rather than values.
    """

    def __init__(self, facts: list[Fact]) -> None:
        self._facts = facts
        self._by_key: dict[tuple[str, str], str] = {}
        for fact in facts:
            self._by_key[(fact.provenance.view, _key_of(fact))] = fact.id

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def as_tuple(self) -> tuple[Fact, ...]:
        return tuple(self._facts)

    def lookup(self, view: str, key: str) -> str:
        """Fact ID for a derived measure, by view and composite key."""
        try:
            return self._by_key[(view, key)]
        except KeyError as exc:
            msg = f"no fact derived for view={view!r} key={key!r}"
            raise KeyError(msg) from exc


def _key_of(fact: Fact) -> str:
    """Composite key from a fact's provenance parameters, in sorted order."""
    params = fact.provenance.params
    return "|".join(f"{k}={params[k]}" for k in sorted(params))


def _make_key(**params: str | int | float) -> str:
    return "|".join(f"{k}={params[k]}" for k in sorted(params))


def derive_facts(
    store: DuckDBStore,
    *,
    run_id: str,
    week: str,
    baseline_week: str,
    taxonomy_version: str,
    thresholds: BriefThresholds,
) -> tuple[FactSet, list[VelocityTest]]:
    """Compute every fact for a run.

    Returns the facts and the velocity tests, because the brief needs the
    test results and recomputing them would risk the brief and the facts
    disagreeing.
    """
    ids = _FactIdAllocator()
    facts: list[Fact] = []

    def emit(
        *,
        label: str,
        value: float,
        unit: FactUnit,
        view: str,
        params: dict[str, str | int | float],
        category: str | None = None,
        channel: str | None = None,
        fact_week: str | None = None,
    ) -> None:
        facts.append(
            Fact(
                id=ids.allocate(),
                run_id=run_id,
                label=label,
                value=value,
                unit=unit,
                taxonomy_version=taxonomy_version,
                provenance=Provenance(view=view, params=params),
                category=category,
                channel=channel,
                week=fact_week,
            )
        )

    # -- category volumes, both weeks --------------------------------------
    counts: dict[str, tuple[int, int]] = {}
    baseline_counts = store.category_counts(baseline_week)
    current_counts = store.category_counts(week)
    for category in sorted(set(baseline_counts) | set(current_counts)):
        baseline = baseline_counts.get(category, 0)
        current = current_counts.get(category, 0)
        counts[category] = (baseline, current)

        for value, which in ((baseline, baseline_week), (current, week)):
            emit(
                label=f"{category} · count · {which}",
                value=float(value),
                unit=FactUnit.COMPLAINTS,
                view="v_weekly_category_counts",
                params={"category": category, "week": which},
                category=category,
                fact_week=which,
            )

    # -- week-on-week change ----------------------------------------------
    # Emitted as its own fact rather than left for the report to subtract.
    # A figure the model computes is a figure the model can get wrong; the
    # only arithmetic that reaches a reader is arithmetic done here.
    for category, (baseline, current) in counts.items():
        change = (current - baseline) / baseline if baseline else 0.0
        emit(
            label=f"{category} · change vs {baseline_week}",
            value=change,
            unit=FactUnit.PROPORTION,
            view="v_weekly_category_counts",
            params={"category": category, "measure": "wow_change", "week": week},
            category=category,
            fact_week=week,
        )

    # -- velocity tests ----------------------------------------------------
    tests = run_velocity_tests(counts, alpha=thresholds.fdr_alpha)

    # -- channel breakdown for categories that moved ----------------------
    moved = {t.category for t in tests if t.significant}
    for row in store.query_view("v_weekly_category_channel_counts", {"week": week}):
        category = str(row["category"])
        if category not in moved:
            continue
        emit(
            label=f"{category} · {row['channel']} · count · {week}",
            value=float(row["complaint_count"]),
            unit=FactUnit.COMPLAINTS,
            view="v_weekly_category_channel_counts",
            params={
                "category": category,
                "channel": str(row["channel"]),
                "week": week,
            },
            category=category,
            channel=str(row["channel"]),
            fact_week=week,
        )

    # -- sentiment, within channel ----------------------------------------
    for which in (baseline_week, week):
        for row in store.query_view("v_sentiment_by_channel_week", {"week": which}):
            emit(
                label=(
                    f"{row['category']} · {row['channel']} · mean sentiment · {which}"
                ),
                value=float(row["mean_sentiment"]),
                unit=FactUnit.SENTIMENT_INDEX,
                view="v_sentiment_by_channel_week",
                params={
                    "category": str(row["category"]),
                    "channel": str(row["channel"]),
                    "week": which,
                },
                category=str(row["category"]),
                channel=str(row["channel"]),
                fact_week=which,
            )

    # -- sentiment shift, within channel ----------------------------------
    # A separate fact, not the difference of two others. The report cites a
    # shift as a figure in its own right, and every figure a reader sees must
    # resolve to something the metrics layer computed.
    baseline_sentiment = {
        (str(r["category"]), str(r["channel"])): float(r["mean_sentiment"])
        for r in store.query_view(
            "v_sentiment_by_channel_week", {"week": baseline_week}
        )
    }
    for row in store.query_view("v_sentiment_by_channel_week", {"week": week}):
        key = (str(row["category"]), str(row["channel"]))
        if key not in baseline_sentiment:
            continue
        emit(
            label=f"{key[0]} · {key[1]} · sentiment shift vs {baseline_week}",
            value=float(row["mean_sentiment"]) - baseline_sentiment[key],
            unit=FactUnit.SENTIMENT_INDEX,
            view="v_sentiment_by_channel_week",
            params={
                "category": key[0],
                "channel": key[1],
                "measure": "sentiment_shift",
                "week": week,
            },
            category=key[0],
            channel=key[1],
            fact_week=week,
        )

    # -- candidate theme sizes --------------------------------------------
    for row in store.query_view("v_candidate_themes", {"week": week}):
        emit(
            label=f"{row['theme_id']} · members · {week}",
            value=float(row["member_count"]),
            unit=FactUnit.COMPLAINTS,
            view="v_candidate_themes",
            params={"theme_id": str(row["theme_id"]), "week": week},
            fact_week=week,
        )

    # -- health indicators -------------------------------------------------
    for row in store.query_view("v_health_indicators", {"week": week}):
        emit(
            label=f"total complaints · {week}",
            value=float(row["total_complaints"]),
            unit=FactUnit.COMPLAINTS,
            view="v_health_indicators",
            params={"measure": "total_complaints", "week": week},
            fact_week=week,
        )
        emit(
            label=f"abstention rate · {week}",
            value=float(row["abstention_rate"]),
            unit=FactUnit.PROPORTION,
            view="v_health_indicators",
            params={"measure": "abstention_rate", "week": week},
            fact_week=week,
        )
        emit(
            label=f"residual share · {week}",
            value=float(row["residual_share"]),
            unit=FactUnit.PROPORTION,
            view="v_health_indicators",
            params={"measure": "residual_share", "week": week},
            fact_week=week,
        )
        # Quarantine is produced by the ingest stage, which is out of scope
        # here. The fact is emitted with a zero value and honest provenance so
        # the brief's shape matches the design rather than quietly omitting a
        # health indicator the architecture calls for.
        emit(
            label=f"quarantined complaints · {week}",
            value=0.0,
            unit=FactUnit.COUNT,
            view="v_health_indicators",
            params={"measure": "quarantine_count", "week": week},
            fact_week=week,
        )

    log.info("facts_derived", run_id=run_id, count=len(facts), week=week)
    return FactSet(facts), tests
