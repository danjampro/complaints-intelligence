"""Shared helpers for the agent nodes.

The single traced model call lives here, so no node can invoke the LLM without
spending budget and appending to the trace. Formatting of brief sections lives
here too, so the same fact is described identically wherever it appears.
"""

from __future__ import annotations

from pydantic import BaseModel

from complaints_intelligence.agent.state import RunContext
from complaints_intelligence.domain.brief import (
    CandidateTheme,
    FlaggedCategory,
    MetricsBrief,
    SentimentSignal,
)
from complaints_intelligence.domain.fact import Fact
from complaints_intelligence.domain.trace import LLMCall
from complaints_intelligence.logging import get_logger
from complaints_intelligence.prompts.loader import load

log = get_logger(__name__)


def call_model[T: BaseModel](
    context: RunContext,
    *,
    node: str,
    prompt_id: str,
    schema: type[T],
    **variables: str,
) -> T:
    """Render a prompt, call the model, and record the call.

    The only path from a node to the LLM. Budget is spent before the call, so
    an exhausted budget stops the request rather than paying for it and then
    complaining.
    """
    context.ledger.spend_llm(node)
    version = context.settings.llm.prompt_version
    prompt = load(prompt_id, version)
    rendered = prompt.render(**variables)

    response = context.llm.complete(
        prompt_id=prompt_id,
        prompt_version=version,
        rendered=rendered,
        schema=schema,
    )
    context.llm_calls.append(
        LLMCall(
            sequence=len(context.llm_calls),
            node=node,
            prompt_id=prompt_id,
            prompt_version=version,
            schema_name=schema.__name__,
            cassette_key=response.cassette_key,
            prompt_chars=response.prompt_chars,
        )
    )
    return response.parsed


def enter(context: RunContext, node: str) -> None:
    """Mark entry to a node, for trace attribution."""
    context.node_sequence.append(node)
    context.tools.entering(node)
    log.info("node_entered", node=node)


# --------------------------------------------------------------------------
# Formatting the brief for prompts.
#
# Every figure is rendered as its fact ID and its label — never its value.
# The model is choosing which stored figure to cite; showing it the number
# would invite it to retype the number.
# --------------------------------------------------------------------------


def _fact_label(facts: dict[str, Fact], fact_id: str) -> str:
    fact = facts.get(fact_id)
    return f"{fact_id} ({fact.label})" if fact else fact_id


def format_facts(facts: dict[str, Fact], fact_ids: list[str]) -> str:
    """List fact IDs with their labels, for the prompt's fact block."""
    if not fact_ids:
        return "(none available)"
    lines = []
    for fact_id in fact_ids:
        fact = facts.get(fact_id)
        if fact is None:
            continue
        lines.append(f"- `{fact_id}` — {fact.label} [unit: {fact.unit.value}]")
    return "\n".join(lines) if lines else "(none available)"


def format_flagged(items: tuple[FlaggedCategory, ...], facts: dict[str, Fact]) -> str:
    if not items:
        return "(none)"
    lines = []
    for item in items:
        significance = (
            "significant after multiple-testing correction"
            if item.significant
            else "TESTED AND NOT SIGNIFICANT after correction"
        )
        channel = (
            f", concentrated in {item.concentrated_in_channel}"
            if item.concentrated_in_channel
            else ""
        )
        lines.append(
            f"- **{item.category}** — {item.direction.value}{channel}. "
            f"{significance}.\n"
            f"  current: {_fact_label(facts, item.count_fact_id)}; "
            f"baseline: {_fact_label(facts, item.baseline_count_fact_id)}; "
            f"change: {_fact_label(facts, item.change_fact_id)}"
        )
    return "\n".join(lines)


def format_sentiment(items: tuple[SentimentSignal, ...], facts: dict[str, Fact]) -> str:
    if not items:
        return "(no sentiment shifts cleared the threshold and the test)"
    return "\n".join(
        f"- **{item.scope}** via {item.channel} — moved {item.direction.value}. "
        f"current: {_fact_label(facts, item.current_fact_id)}; "
        f"baseline: {_fact_label(facts, item.baseline_fact_id)}; "
        f"shift: {_fact_label(facts, item.shift_fact_id)}"
        for item in items
    )


def format_themes(items: tuple[CandidateTheme, ...], facts: dict[str, Fact]) -> str:
    if not items:
        return "(none)"
    lines = []
    for item in items:
        lines.append(
            f"- **{item.theme_id}** — {item.provisional_label}\n"
            f"  size: {_fact_label(facts, item.size_fact_id)}; "
            f"coherence {item.coherence:.2f}; "
            f"seen for {item.persistence_weeks} consecutive week(s); "
            f"channel concentration {item.channel_concentration:.2f}; "
            f"duplicate ratio {item.duplicate_ratio:.2f}"
        )
    return "\n".join(lines)


def format_health(brief: MetricsBrief, facts: dict[str, Fact]) -> str:
    health = brief.health
    return "\n".join(
        (
            f"- total complaints: "
            f"{_fact_label(facts, health.total_complaints_fact_id)}",
            f"- abstention rate: {_fact_label(facts, health.abstention_rate_fact_id)}",
            f"- residual share: {_fact_label(facts, health.residual_share_fact_id)}",
            f"- quarantined: {_fact_label(facts, health.quarantine_count_fact_id)}",
        )
    )


def format_headlines(brief: MetricsBrief, facts: dict[str, Fact]) -> str:
    return "\n".join(
        f"- {_fact_label(facts, fact_id)}" for fact_id in brief.headline_fact_ids
    )
