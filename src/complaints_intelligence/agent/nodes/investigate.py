"""The ``investigate`` node.

For each planned category: retrieve exemplar complaints, characterise what
customers are describing, draft a finding with citations.

The retrieved complaints are kept on the context so a later revision re-prompts
with the *same* evidence. Retrieving afresh would let a revision quietly change
what the finding is about while appearing to fix a formatting problem.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.agent.nodes.common import call_model, enter, format_facts
from complaints_intelligence.agent.schemas import InvestigateOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.agent.untrusted import render_complaints
from complaints_intelligence.domain.brief import FlaggedCategory
from complaints_intelligence.domain.finding import (
    Citation,
    Claim,
    Finding,
    FindingKind,
)
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.synth.taxonomy import get_node

log = get_logger(__name__)

NODE = "investigate"


def relevant_fact_ids(state: RunState, category: str) -> list[str]:
    """Fact IDs the model may cite for one category.

    Scoped deliberately. Handing the model every fact in the run would let a
    finding about failed payments cite a figure about branch closures, which
    would resolve, pass the critic, and still be wrong.
    """
    ids: list[str] = []
    for flagged in state.brief.flagged_categories:
        if flagged.category != category:
            continue
        ids.extend(
            [
                flagged.count_fact_id,
                flagged.baseline_count_fact_id,
                flagged.change_fact_id,
            ]
        )
    for signal in state.brief.sentiment_signals:
        if signal.scope == category:
            ids.extend(
                [signal.current_fact_id, signal.baseline_fact_id, signal.shift_fact_id]
            )
    ids.extend(state.brief.headline_fact_ids)
    return list(dict.fromkeys(ids))


def _to_finding(
    output: InvestigateOutput, *, finding_id: str, category: str
) -> Finding:
    """Map model output onto the domain object.

    An explicit step. The model does not choose the finding's identity or its
    kind, and mapping here rather than parsing straight into the domain type
    is what keeps those fields out of its reach.
    """
    claims = [
        Claim(
            text=claim.text,
            fact_refs=tuple(claim.fact_refs),
            citations=tuple(
                Citation(
                    complaint_id=c.complaint_id,
                    start=c.start,
                    end=max(c.end, c.start + 1),
                )
                for c in claim.citations
            ),
        )
        for claim in output.claims
    ]
    # Hypotheses become claims flagged as requiring confirmation. They are
    # published as needing a named owner rather than suppressed: a suppressed
    # hypothesis reappears as causal language in the next draft.
    claims.extend(
        Claim(text=hypothesis, requires_confirmation=True)
        for hypothesis in output.hypotheses
    )

    return Finding(
        finding_id=finding_id,
        kind=FindingKind.DRIVER,
        headline=output.headline,
        claims=tuple(claims),
        category=category,
    )


def _flagged_for(state: RunState, category: str) -> FlaggedCategory | None:
    for flagged in state.brief.flagged_categories:
        if flagged.category == category:
            return flagged
    return None


def investigate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Draft a finding for each planned category."""
    enter(context, NODE)
    findings: list[Finding] = []
    facts = {f.id: f for f in context.store.all_facts()}

    categories = [item.target for item in state.plan if item.kind == "category"]
    for index, category in enumerate(categories, start=1):
        flagged = _flagged_for(state, category)
        if flagged is None:
            continue

        node_definition = get_node(category)
        finding_id = f"F-{index:02d}"

        # The query is built from the taxonomy definition, not from model
        # output. A model-authored retrieval query would let a prompt
        # injection steer which evidence the finding rests on.
        query = f"{node_definition.display_name}. {node_definition.inclusion}"

        try:
            exemplars = context.tools.get_exemplars(
                query_text=query,
                week=state.brief.week,
                category=category,
                limit=context.settings.budget.max_exemplars_per_finding,
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"investigation of {category} stopped: {exc}")
            break

        if not exemplars:
            context.ledger.note(
                f"no exemplars retrieved for {category}; finding omitted"
            )
            continue

        context.evidence[finding_id] = exemplars

        try:
            output = call_model(
                context,
                node=NODE,
                prompt_id="investigate",
                schema=InvestigateOutput,
                category=category,
                category_display_name=node_definition.display_name,
                category_inclusion=node_definition.inclusion,
                category_exclusion=node_definition.exclusion,
                week=state.brief.week,
                baseline_week=state.brief.baseline_week,
                fact_block=format_facts(facts, relevant_fact_ids(state, category)),
                evidence_block=render_complaints(exemplars),
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"investigation of {category} stopped: {exc}")
            break

        findings.append(_to_finding(output, finding_id=finding_id, category=category))

    log.info("investigate_complete", findings=len(findings))
    return {"findings": findings}
