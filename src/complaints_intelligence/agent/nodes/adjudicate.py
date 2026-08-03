"""The ``adjudicate`` node.

For each candidate theme: real signal, noise, or ingest artefact?

This is the node that most justifies an agent. Clustering can tell you a group
exists; it cannot tell you whether the group is customers complaining or one
CRM note duplicated by a batch re-run. That judgement needs the evidence read
and weighed against the cluster's measured properties, and the answer branches
on what the evidence turns out to be.

A ``real_signal`` verdict sends the theme to the report as narrative with
evidence. It does **not** adopt it as a taxonomy category — that is a separate,
human-gated act, deliberately slower, because adoption is structural and
reporting must be fast.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.agent.nodes.common import call_model, enter, format_facts
from complaints_intelligence.agent.schemas import AdjudicateOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.agent.untrusted import render_complaints
from complaints_intelligence.domain.brief import CandidateTheme
from complaints_intelligence.domain.finding import (
    Adjudication,
    Citation,
    Claim,
    Finding,
    FindingKind,
    ThemeVerdict,
)
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.synth.taxonomy import TAXONOMY

log = get_logger(__name__)

NODE = "adjudicate"

_VALID_VERDICTS = {v.value for v in ThemeVerdict}


def _format_metrics(theme: CandidateTheme) -> str:
    """Describe a cluster's measured properties in words the model can weigh.

    Interpretation is attached to each number rather than left implicit. The
    raw value of a duplicate ratio means nothing without knowing which
    direction is suspicious, and a model asked to infer that from context
    will sometimes infer it backwards.
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
            f"- coherence: {theme.coherence:.2f} "
            f"(mean similarity between members; note that duplicated text "
            f"scores high here without being a real theme)",
            f"- duplicate ratio: {theme.duplicate_ratio:.2f} — {duplication}",
            f"- channel concentration: {theme.channel_concentration:.2f} — "
            f"{concentration}",
            f"- persistence: {persistence}",
        )
    )


def _format_taxonomy() -> str:
    return "\n".join(f"- {node.category}: {node.inclusion}" for node in TAXONOMY)


def adjudicate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Rule on each planned candidate theme."""
    enter(context, NODE)
    adjudications: list[Adjudication] = []
    emerging: list[Finding] = []
    facts = {f.id: f for f in context.store.all_facts()}

    planned = {item.target for item in state.plan if item.kind == "candidate_theme"}
    themes = [t for t in state.brief.candidate_themes if t.theme_id in planned]

    for index, theme in enumerate(themes, start=1):
        try:
            members = context.tools.get_exemplars(
                query_text=theme.provisional_label,
                week=state.brief.week,
                theme_id=theme.theme_id,
                limit=context.settings.budget.max_exemplars_per_finding,
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"adjudication of {theme.theme_id} stopped: {exc}")
            break

        if not members:
            context.ledger.note(
                f"no members retrieved for {theme.theme_id}; not adjudicated"
            )
            continue

        try:
            output = call_model(
                context,
                node=NODE,
                prompt_id="adjudicate",
                schema=AdjudicateOutput,
                theme_id=theme.theme_id,
                provisional_label=theme.provisional_label,
                week=state.brief.week,
                metrics_block=_format_metrics(theme),
                taxonomy_block=_format_taxonomy(),
                fact_block=format_facts(facts, [theme.size_fact_id]),
                evidence_block=render_complaints(members),
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"adjudication of {theme.theme_id} stopped: {exc}")
            break

        # An unrecognised verdict is treated as noise rather than coerced to a
        # neighbour. Guessing what the model meant would be guessing about the
        # one decision this node exists to make.
        if output.verdict not in _VALID_VERDICTS:
            context.ledger.note(
                f"{theme.theme_id}: model returned unrecognised verdict "
                f"{output.verdict!r}; treated as noise"
            )
            verdict = ThemeVerdict.NOISE
        else:
            verdict = ThemeVerdict(output.verdict)

        citations = tuple(
            Citation(
                complaint_id=c.complaint_id, start=c.start, end=max(c.end, c.start + 1)
            )
            for c in output.citations
        )
        adjudications.append(
            Adjudication(
                theme_id=theme.theme_id,
                verdict=verdict,
                rationale=output.rationale,
                citations=citations,
                duplicate_of_category=output.duplicate_of_category,
            )
        )

        # Only a real signal reaches the report as a finding. The others are
        # retained as adjudications so the report can state what was examined
        # and rejected — a theme dismissed silently is indistinguishable from
        # a theme never looked at.
        if verdict is ThemeVerdict.REAL_SIGNAL:
            emerging.append(
                Finding(
                    finding_id=f"E-{index:02d}",
                    kind=FindingKind.EMERGING_THEME,
                    headline=output.headline or theme.provisional_label,
                    claims=(
                        Claim(
                            text=output.rationale,
                            fact_refs=(theme.size_fact_id,),
                            citations=citations,
                        ),
                    ),
                    theme_id=theme.theme_id,
                )
            )

    log.info(
        "adjudicate_complete",
        adjudicated=len(adjudications),
        real_signals=len(emerging),
        verdicts=[a.verdict.value for a in adjudications],
    )
    return {"adjudications": adjudications, "findings": [*state.findings, *emerging]}
