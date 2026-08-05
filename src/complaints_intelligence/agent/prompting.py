"""Everything the nodes share: the single traced model call, and the formatting
of brief material for prompts.

The model call lives here so no node can reach the LLM without spending budget
first, and the formatters live here so the same fact is described identically
wherever it appears.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel

from complaints_intelligence.agent.schemas import DraftCitation, InvestigateOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.fixtures.taxonomy import get_node
from complaints_intelligence.inputs import CandidateTheme, Fact, FactUnit
from complaints_intelligence.outputs import Citation, Claim, Finding, FindingKind
from complaints_intelligence.prompts.loader import load

log = logging.getLogger(__name__)


def call_model[T: BaseModel](
    context: RunContext, *, node: str, prompt_id: str, schema: type[T], **variables: str
) -> T:
    """Render a prompt and call the model. The only path from a node to the
    LLM, and budget is spent before the call rather than after paying for it."""
    context.ledger.spend_llm(node)
    version = context.settings.llm.prompt_version
    response = context.llm.complete(
        prompt_id=prompt_id,
        prompt_version=version,
        rendered=load(prompt_id, version).render(**variables),
        schema=schema,
    )
    return response.parsed


def enter(context: RunContext, node: str) -> None:
    """Mark entry to a node, for the trace."""
    context.node_sequence.append(node)
    context.tools.entering(node)
    log.info("entering node %s", node)


def citations_of(drafted: Sequence[DraftCitation]) -> tuple[Citation, ...]:
    """Map drafted citations onto the domain type, forcing a non-empty span."""
    return tuple(
        Citation(
            complaint_id=c.complaint_id, start=c.start, end=max(c.end, c.start + 1)
        )
        for c in drafted
    )


def facts_by_id(context: RunContext) -> dict[str, Fact]:
    return {fact.id: fact for fact in context.store.all_facts()}


def _worked_form(fact: Fact) -> str:
    """A filled-in phrase showing where a reference sits once it is a number.

    The prompts state the rule and the model still broke it; a worked phrase
    gives it the shape directly, and the unit is what decides the shape.
    """
    match fact.unit:
        case FactUnit.PROPORTION:
            return f"a change of {{{{{fact.id}}}}}"
        case FactUnit.SENTIMENT_INDEX:
            return f"moved to {{{{{fact.id}}}}}"
        case _:
            return f"{{{{{fact.id}}}}} complaints"


def format_facts(facts: dict[str, Fact], fact_ids: list[str]) -> str:
    """List fact IDs with their labels — never their values.

    The model is choosing which stored figure to cite; showing it the number
    would invite it to retype the number.
    """
    lines = [
        f"- `{fact_id}` — {facts[fact_id].label} — "
        f"write as: {_worked_form(facts[fact_id])}"
        for fact_id in fact_ids
        if fact_id in facts
    ]
    return "\n".join(lines) if lines else "(none available)"


def relevant_fact_ids(state: RunState, category: str) -> list[str]:
    """Fact IDs the model may cite for one category.

    Scoped deliberately: handing it every fact in the run would let a finding
    about failed payments cite a figure about branch closures, which would
    resolve, pass the critic, and still be wrong.
    """
    ids: list[str] = []
    for flagged in state.brief.flagged_categories:
        if flagged.category == category:
            ids += [
                flagged.count_fact_id,
                flagged.baseline_count_fact_id,
                flagged.change_fact_id,
            ]
    for signal in state.brief.sentiment_signals:
        if signal.scope == category:
            ids += [
                signal.current_fact_id,
                signal.baseline_fact_id,
                signal.shift_fact_id,
            ]
    ids += list(state.brief.headline_fact_ids)
    return list(dict.fromkeys(ids))


def retrieval_query(category: str) -> str:
    """Build the retrieval query from the taxonomy, never from model output.

    A model-authored query would let a prompt injection steer which evidence a
    finding rests on.
    """
    node = get_node(category)
    return f"{node.display_name}. {node.inclusion}"


def format_theme_metrics(theme: CandidateTheme) -> str:
    """Describe a cluster's measured properties in words the model can weigh.

    Interpretation is attached to each number rather than left implicit: the raw
    value of a duplicate ratio means nothing without knowing which direction is
    suspicious, and a model asked to infer that will sometimes infer it
    backwards.
    """
    duplication = (
        "very high — most members are near-identical text, which points at "
        "duplication rather than at many customers"
        if theme.duplicate_ratio > 0.5
        else "low — members are distinct texts"
        if theme.duplicate_ratio < 0.2
        else "moderate"
    )
    concentration = (
        "single channel — every instance arrived through one intake path"
        if theme.channel_concentration > 0.9
        else "spread across channels"
        if theme.channel_concentration < 0.6
        else "somewhat concentrated"
    )
    persistence = (
        "first appearance this week"
        if theme.persistence_weeks <= 1
        else f"seen for {theme.persistence_weeks} consecutive weeks"
    )
    return "\n".join(
        (
            f"- coherence: {theme.coherence:.2f} (mean similarity between members; "
            f"note that duplicated text scores high here without being a real theme)",
            f"- duplicate ratio: {theme.duplicate_ratio:.2f} — {duplication}",
            f"- channel concentration: {theme.channel_concentration:.2f} — "
            f"{concentration}",
            f"- persistence: {persistence}",
        )
    )


def to_finding(output: InvestigateOutput, *, finding_id: str, category: str) -> Finding:
    """Map model output onto the domain object.

    An explicit step: the model does not choose a finding's identity or kind,
    and mapping here is what keeps those fields out of its reach.
    """
    claims = [
        Claim(
            text=claim.text,
            fact_refs=tuple(claim.fact_refs),
            citations=citations_of(claim.citations),
        )
        for claim in output.claims
    ]
    # Hypotheses become claims flagged as requiring confirmation, published
    # rather than suppressed: a suppressed hypothesis reappears as causal
    # language in the next draft.
    claims += [
        Claim(text=hypothesis, requires_confirmation=True)
        for hypothesis in output.hypotheses
    ]
    return Finding(
        finding_id=finding_id,
        kind=FindingKind.DRIVER,
        headline=output.headline,
        claims=tuple(claims),
        category=category,
    )
