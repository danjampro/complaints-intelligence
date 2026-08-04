"""The ``remediate`` node.

For each finding: retrieve comparable closed complaints with the notes
recording how they were resolved, assess whether that precedent genuinely
transfers, and summarise what was done.

Retrieval matches complaint against complaint and reaches the note by a join,
so the model sees the pair — the problem and the response to it. Judging
whether a precedent applies is a question about the problem, and a note read
without it is a description of an action with nothing to apply it to.

This node is why the design needs an agent rather than a prompt chain. The
step is retrieve → assess relevance → refine, and the number of iterations
depends on what comes back. If the first retrieval returns precedents that do
not apply, the right response is to search differently, and how many times that
happens is not enumerable in advance.

Retries are bounded and the widening is deliberate: the first pass is scoped to
the finding's own category, the second drops that filter. A precedent from a
neighbouring category may still transfer — the same gateway timeout can surface
as both a failed payment and a declined card — but it is second choice, and the
report records which pass produced it.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.agent.nodes.common import call_model, enter, format_facts
from complaints_intelligence.agent.schemas import RemediateOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.agent.untrusted import render_precedents
from complaints_intelligence.domain.complaint import Precedent
from complaints_intelligence.domain.finding import (
    Citation,
    Finding,
    Remediation,
    ResolutionPrecedent,
)
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.synth.taxonomy import get_node

log = get_logger(__name__)

NODE = "remediate"

#: Share of retrieved precedents that must transfer for the retrieval to be
#: considered adequate. Below this, the node widens its search and tries again.
_TRANSFER_THRESHOLD = 0.34


def _finding_summary(finding: Finding) -> str:
    claims = "\n".join(f"- {claim.text}" for claim in finding.claims)
    return f"**{finding.headline}**\n\n{claims}"


def _retrieve(
    context: RunContext, finding: Finding, *, scoped: bool
) -> tuple[Precedent, ...]:
    """Retrieve precedents, optionally scoped to the finding's category."""
    if finding.category:
        node_definition = get_node(finding.category)
        query = f"{node_definition.display_name}. {node_definition.inclusion}"
    else:
        query = finding.headline

    return context.tools.get_precedent(
        query_text=query,
        category=finding.category if scoped else None,
        limit=context.settings.budget.max_precedents_per_finding,
    )


def remediate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Draft a remediation recommendation for each finding."""
    enter(context, NODE)
    remediations: list[Remediation] = []
    facts = {f.id: f for f in context.store.all_facts()}

    for finding in state.findings:
        fact_ids = list(
            dict.fromkeys([ref for claim in finding.claims for ref in claim.fact_refs])
        )

        output: RemediateOutput | None = None
        precedents: tuple[Precedent, ...] = ()
        widened = False

        for attempt, scoped in enumerate((True, False), start=1):
            try:
                precedents = _retrieve(context, finding, scoped=scoped)
            except BudgetExceededError as exc:
                context.ledger.note(f"remediation for {finding.finding_id}: {exc}")
                break

            if not precedents:
                continue

            try:
                output = call_model(
                    context,
                    node=NODE,
                    prompt_id="remediate",
                    schema=RemediateOutput,
                    finding_block=_finding_summary(finding),
                    fact_block=format_facts(facts, fact_ids),
                    evidence_block=render_precedents(precedents),
                )
            except BudgetExceededError as exc:
                context.ledger.note(f"remediation for {finding.finding_id}: {exc}")
                break

            transferring = sum(1 for p in output.precedents if p.transfers)
            share = transferring / len(output.precedents) if output.precedents else 0.0
            if share >= _TRANSFER_THRESHOLD:
                break

            # Too few precedents apply. Widen the search rather than accepting
            # a recommendation resting on evidence the model has just told us
            # is irrelevant.
            if attempt == 1:
                widened = True
                context.ledger.note(
                    f"remediation for {finding.finding_id}: only "
                    f"{transferring} of {len(output.precedents)} precedents "
                    f"transferred; widening retrieval beyond the category"
                )
                output = None

        if output is None:
            context.ledger.note(
                f"no transferable precedent found for {finding.finding_id}; "
                f"no recommendation made"
            )
            continue

        remediations.append(
            Remediation(
                finding_id=finding.finding_id,
                recommendation=output.recommendation,
                precedents=tuple(
                    ResolutionPrecedent(
                        complaint_id=p.complaint_id,
                        transfers=p.transfers,
                        reason=p.reason,
                    )
                    for p in output.precedents
                ),
                citations=tuple(
                    Citation(
                        complaint_id=c.complaint_id,
                        start=c.start,
                        end=max(c.end, c.start + 1),
                    )
                    for c in output.citations
                ),
                fact_refs=tuple(output.fact_refs),
                suggested_owner=output.suggested_owner,
            )
        )
        log.info(
            "remediation_drafted",
            finding_id=finding.finding_id,
            precedents=len(output.precedents),
            widened=widened,
        )

    log.info("remediate_complete", remediations=len(remediations))
    return {"remediations": remediations}
