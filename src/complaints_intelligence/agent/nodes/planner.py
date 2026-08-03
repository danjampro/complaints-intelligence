"""The ``plan`` node.

Reads the metrics brief and allocates a bounded set of investigations. This is
the only node that sees the brief whole; everything downstream works on one
item at a time.

The plan is advisory in one direction only. The model chooses *what to look at
and in what order*; it cannot add anything the brief did not carry, because
the targets it names are validated against the brief before use. Agency is
confined to what to investigate next — determinism governs what the numbers
are.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.agent.nodes.common import (
    call_model,
    enter,
    format_flagged,
    format_headlines,
    format_health,
    format_sentiment,
    format_themes,
)
from complaints_intelligence.agent.schemas import PlannedInvestigation, PlanOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)

NODE = "plan"


def _fallback_plan(state: RunState) -> list[PlannedInvestigation]:
    """Deterministic plan used when the model cannot be consulted.

    Significant movements first, then the largest candidate themes. Not as
    good as a considered plan, but a run that loses its planner should degrade
    to a defensible ordering rather than to nothing.
    """
    plan: list[PlannedInvestigation] = []
    for flagged in state.brief.flagged_categories:
        if flagged.significant:
            plan.append(
                PlannedInvestigation(
                    target=flagged.category,
                    kind="category",
                    reason="Significant movement after multiple-testing correction.",
                )
            )
    for theme in state.brief.candidate_themes:
        plan.append(
            PlannedInvestigation(
                target=theme.theme_id,
                kind="candidate_theme",
                reason="Candidate theme carried by the brief.",
            )
        )
    return plan


def plan_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Choose what to investigate this week."""
    enter(context, NODE)
    brief = state.brief
    facts = {f.id: f for f in context.store.all_facts()}

    try:
        output = call_model(
            context,
            node=NODE,
            prompt_id="plan",
            schema=PlanOutput,
            week=brief.week,
            baseline_week=brief.baseline_week,
            taxonomy_version=brief.taxonomy_version,
            max_investigations=str(context.settings.budget.max_investigations),
            headline_block=format_headlines(brief, facts),
            flagged_block=format_flagged(brief.flagged_categories, facts),
            sentiment_block=format_sentiment(brief.sentiment_signals, facts),
            themes_block=format_themes(brief.candidate_themes, facts),
            health_block=format_health(brief, facts),
        )
        investigations = output.investigations
        skipped = [(s.target, s.reason) for s in output.skipped]
    except BudgetExceededError as exc:
        context.ledger.note(f"plan fell back to the default ordering: {exc}")
        investigations = _fallback_plan(state)
        skipped = []

    # The model may only plan against what the brief carried. An invented
    # target would send a later node retrieving evidence for something the
    # metrics layer never measured, and the resulting finding would have no
    # facts behind it.
    known_categories = {f.category for f in state.brief.flagged_categories}
    known_themes = {t.theme_id for t in state.brief.candidate_themes}

    valid: list[PlannedInvestigation] = []
    for item in investigations:
        if item.target in known_categories or item.target in known_themes:
            valid.append(item)
        else:
            context.ledger.note(
                f"plan proposed {item.target!r}, which the brief does not "
                f"carry; dropped"
            )

    # Truncate the two kinds independently. A single combined cap lets
    # categories — always more numerous — consume the whole budget and leave
    # candidate themes unexamined, which is precisely the content the report
    # has no other route to.
    budget = context.settings.budget
    categories = [i for i in valid if i.kind == "category"]
    themes = [i for i in valid if i.kind != "category"]

    kept_categories = categories[: budget.max_investigations]
    kept_themes = themes[: budget.max_adjudications]

    for dropped in categories[len(kept_categories) :]:
        skipped.append((dropped.target, "beyond the investigation budget"))
    for dropped in themes[len(kept_themes) :]:
        skipped.append((dropped.target, "beyond the adjudication budget"))

    capped = [*kept_categories, *kept_themes]
    log.info(
        "plan_complete",
        investigations=len(kept_categories),
        adjudications=len(kept_themes),
        skipped=len(skipped),
        dropped_invalid=len(investigations) - len(valid),
    )
    return {"plan": capped, "plan_skipped": skipped}
