"""The three nodes that draft the report: investigate, adjudicate, remediate.

Verification and repair live in ``agent/verify.py``; what they share with these
is in ``agent/prompting.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from complaints_intelligence.agent.prompting import (
    call_model,
    citations_of,
    enter,
    facts_by_id,
    format_facts,
    format_theme_metrics,
    relevant_fact_ids,
    retrieval_query,
    to_finding,
)
from complaints_intelligence.agent.schemas import (
    AdjudicateOutput,
    InvestigateOutput,
    RemediateOutput,
)
from complaints_intelligence.agent.state import (
    BudgetExceededError,
    RunContext,
    RunState,
)
from complaints_intelligence.agent.untrusted import render_complaints, render_precedents
from complaints_intelligence.fixtures.taxonomy import TAXONOMY, get_node
from complaints_intelligence.inputs import Precedent
from complaints_intelligence.outputs import (
    Adjudication,
    Claim,
    Finding,
    FindingKind,
    Remediation,
    ResolutionPrecedent,
    ThemeVerdict,
)

log = logging.getLogger(__name__)

#: Share of retrieved precedents that must transfer before a recommendation
#: rests on them. Below this, the remediation node widens and tries again.
_TRANSFER_THRESHOLD = 0.34


def investigate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Draft a finding for each of the top-ranked flagged categories.

    The brief arrives ordered most significant first, so the investigation
    budget drops the weakest movements rather than an arbitrary tail.
    """
    enter(context, "investigate")
    facts = facts_by_id(context)
    limit = context.settings.budget.max_investigations
    flagged = list(state.brief.flagged_categories)

    for dropped in flagged[limit:]:
        context.ledger.note(
            f"{dropped.category} was flagged but fell outside the investigation "
            f"budget of {limit}"
        )

    findings: list[Finding] = []
    for index, category in enumerate(flagged[:limit], start=1):
        finding_id = f"F-{index:02d}"
        node = get_node(category.category)
        try:
            exemplars = context.tools.get_exemplars(
                query_text=retrieval_query(category.category),
                week=state.brief.week,
                category=category.category,
            )
            if not exemplars:
                context.ledger.note(
                    f"no exemplars retrieved for {category.category}; finding omitted"
                )
                continue
            context.evidence[finding_id] = exemplars

            output = call_model(
                context,
                node="investigate",
                prompt_id="investigate",
                schema=InvestigateOutput,
                category=category.category,
                category_display_name=node.display_name,
                category_inclusion=node.inclusion,
                category_exclusion=node.exclusion,
                week=state.brief.week,
                baseline_week=state.brief.baseline_week,
                significance=(
                    "significant after multiple-testing correction"
                    if category.significant
                    else "TESTED AND NOT SIGNIFICANT after correction"
                ),
                fact_block=format_facts(
                    facts, relevant_fact_ids(state, category.category)
                ),
                evidence_block=render_complaints(exemplars),
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"investigation of {category.category} stopped: {exc}")
            break

        findings.append(
            to_finding(output, finding_id=finding_id, category=category.category)
        )

    log.info("investigate complete: %d finding(s)", len(findings))
    return {"findings": findings}


def adjudicate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Rule on each candidate theme: real signal, noise, or ingest artefact?

    This is the node that most justifies an agent. Clustering can tell you a
    group exists; it cannot tell you whether the group is customers complaining
    or one CRM note duplicated by a batch re-run.
    """
    enter(context, "adjudicate")
    facts = facts_by_id(context)
    adjudications: list[Adjudication] = []
    emerging: list[Finding] = []

    themes = list(state.brief.candidate_themes)[
        : context.settings.budget.max_adjudications
    ]
    for index, theme in enumerate(themes, start=1):
        try:
            members = context.tools.get_exemplars(
                query_text=theme.provisional_label,
                week=state.brief.week,
                theme_id=theme.theme_id,
            )
            if not members:
                context.ledger.note(f"no members retrieved for {theme.theme_id}")
                continue

            output = call_model(
                context,
                node="adjudicate",
                prompt_id="adjudicate",
                schema=AdjudicateOutput,
                theme_id=theme.theme_id,
                provisional_label=theme.provisional_label,
                week=state.brief.week,
                metrics_block=format_theme_metrics(theme),
                taxonomy_block="\n".join(
                    f"- {node.category}: {node.inclusion}" for node in TAXONOMY
                ),
                fact_block=format_facts(facts, [theme.size_fact_id]),
                evidence_block=render_complaints(members),
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"adjudication of {theme.theme_id} stopped: {exc}")
            break

        # An unrecognised verdict is treated as noise rather than coerced to a
        # neighbour: guessing what the model meant would be guessing about the
        # one decision this node exists to make.
        try:
            verdict = ThemeVerdict(output.verdict)
        except ValueError:
            context.ledger.note(
                f"{theme.theme_id}: unrecognised verdict {output.verdict!r}; "
                f"treated as noise"
            )
            verdict = ThemeVerdict.NOISE

        citations = citations_of(output.citations)
        adjudications.append(
            Adjudication(
                theme_id=theme.theme_id,
                verdict=verdict,
                rationale=output.rationale,
                citations=citations,
                duplicate_of_category=output.duplicate_of_category,
            )
        )

        # Only a real signal reaches the report as a finding. The rest are kept
        # as adjudications, because a theme dismissed silently is
        # indistinguishable from a theme never looked at.
        if verdict is ThemeVerdict.REAL_SIGNAL:
            emerging.append(
                Finding(
                    finding_id=f"E-{index:02d}",
                    kind=FindingKind.EMERGING_THEME,
                    headline=output.headline or theme.provisional_label,
                    claims=(
                        Claim(
                            text=output.rationale,
                            # Declared only if the rationale actually uses it: a
                            # fact_ref the text never references would claim a
                            # figure the report does not print.
                            fact_refs=(
                                (theme.size_fact_id,)
                                if theme.size_fact_id in output.rationale
                                else ()
                            ),
                            citations=citations,
                        ),
                    ),
                    theme_id=theme.theme_id,
                )
            )

    log.info(
        "adjudicate complete: %d verdict(s), %d real signal(s)",
        len(adjudications),
        len(emerging),
    )
    return {"adjudications": adjudications, "findings": [*state.findings, *emerging]}


def _retrieve_precedents(
    context: RunContext, finding: Finding, *, scoped: bool
) -> tuple[Precedent, ...]:
    query = retrieval_query(finding.category) if finding.category else finding.headline
    return context.tools.get_precedent(
        query_text=query, category=finding.category if scoped else None
    )


def remediate_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Draft a recommendation for each finding from resolution precedent.

    This is why the design needs an agent rather than a prompt chain: the step
    is retrieve → assess → refine, and if the first pass returns precedents that
    do not apply, the right response is to search differently.
    """
    enter(context, "remediate")
    facts = facts_by_id(context)
    remediations: list[Remediation] = []

    for finding in state.findings:
        fact_ids = list(
            dict.fromkeys(ref for claim in finding.claims for ref in claim.fact_refs)
        )
        output: RemediateOutput | None = None

        # First pass scoped to the finding's own category; the second drops the
        # filter, because the same gateway timeout can surface as both a failed
        # payment and a declined card.
        for attempt, scoped in enumerate((True, False), start=1):
            try:
                precedents = _retrieve_precedents(context, finding, scoped=scoped)
                if not precedents:
                    continue
                output = call_model(
                    context,
                    node="remediate",
                    prompt_id="remediate",
                    schema=RemediateOutput,
                    finding_block=(
                        f"**{finding.headline}**\n\n"
                        + "\n".join(f"- {claim.text}" for claim in finding.claims)
                    ),
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

            # Too few apply. Widen rather than accept a recommendation resting
            # on evidence the model has just called irrelevant.
            if attempt == 1:
                context.ledger.note(
                    f"remediation for {finding.finding_id}: only {transferring} of "
                    f"{len(output.precedents)} precedents transferred; widening "
                    f"retrieval beyond the category"
                )
                output = None

        if output is None:
            context.ledger.note(
                f"no transferable precedent for {finding.finding_id}; "
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
                citations=citations_of(output.citations),
                fact_refs=tuple(output.fact_refs),
                suggested_owner=output.suggested_owner,
            )
        )

    log.info("remediate complete: %d recommendation(s)", len(remediations))
    return {"remediations": remediations}
