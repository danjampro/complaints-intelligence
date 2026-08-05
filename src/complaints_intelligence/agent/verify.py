"""The ``critic`` and ``revise`` nodes.

``critic`` runs the programmatic checks in ``critic.py``; ``revise`` re-prompts
the model with the specific failures, on the same retrieved evidence, and is
bounded at two rounds.
"""

from __future__ import annotations

import logging
from typing import Any

from complaints_intelligence.agent.prompting import (
    call_model,
    enter,
    facts_by_id,
    format_facts,
    relevant_fact_ids,
    to_finding,
)
from complaints_intelligence.agent.schemas import InvestigateOutput
from complaints_intelligence.agent.state import (
    BudgetExceededError,
    RunContext,
    RunState,
)
from complaints_intelligence.agent.untrusted import render_complaints
from complaints_intelligence.critic import cited_spans, published_prose, verify
from complaints_intelligence.fixtures.taxonomy import get_node
from complaints_intelligence.outputs import CriticReport, Finding, FindingKind
from complaints_intelligence.render import snap_span

log = logging.getLogger(__name__)


def _texts_to_scan(state: RunState, context: RunContext) -> list[tuple[str, str]]:
    """Every published sentence, plus the source spans citations resolve to.

    A quotation pulled from the store can carry an identifier redaction missed,
    so scanning only the model's own prose would inspect the part of the report
    least likely to contain any. Spans are snapped exactly as the renderer snaps
    them, so no character that reaches the reader escapes the scan.
    """
    texts = [
        (location, text)
        for location, text, _ in published_prose(
            state.findings, state.adjudications, state.remediations
        )
    ]
    for location, citation in cited_spans(state.findings, state.remediations):
        try:
            complaint = context.store.get_complaint(citation.complaint_id)
        except KeyError:
            continue
        start, end = snap_span(complaint.text, citation.start, citation.end)
        texts.append((f"{location}/{citation.complaint_id}", complaint.text[start:end]))
    return texts


def critic_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Verify the draft programmatically. No model is involved."""
    enter(context, "critic")
    return {
        "critic": verify(
            state.findings,
            # Neither a rejected theme's rationale nor a recommendation is a
            # finding, but both are published, so both are verified alongside.
            adjudications=state.adjudications,
            remediations=state.remediations,
            store=context.store,
            thresholds=context.settings.critic,
            revision=state.revision,
            scanned_texts=_texts_to_scan(state, context),
        )
    }


def _failing_findings(state: RunState, report: CriticReport) -> set[str]:
    """Finding IDs named in at least one failure. Only these are re-prompted:
    redrafting a finding that passed would spend budget to risk breaking it."""
    ids = {f.finding_id for f in state.findings}
    return {
        finding_id
        for check in report.failures
        for offence in check.offending
        for finding_id in ids
        if offence.startswith((f"{finding_id}:", f"{finding_id}/"))
    }


def _format_failures(report: CriticReport, finding_id: str) -> str:
    lines: list[str] = []
    for check in report.failures:
        relevant = [
            o
            for o in check.offending
            if o.startswith((f"{finding_id}:", f"{finding_id}/"))
        ]
        if relevant:
            lines.append(f"- **{check.name}**: {check.detail}")
            lines += [f"  - {o}" for o in relevant]
    return "\n".join(lines) if lines else "- (no failures attributed to this finding)"


def _format_draft(finding: Finding) -> str:
    lines = [f"Headline: {finding.headline}", "", "Claims:"]
    for index, claim in enumerate(finding.claims, start=1):
        cited = ", ".join(
            f"{c.complaint_id}[{c.start}:{c.end}]" for c in claim.citations
        )
        lines += [
            f"{index}. {claim.text}",
            f"   fact_refs: {list(claim.fact_refs)}",
            f"   citations: {cited or '(none)'}",
        ]
    return "\n".join(lines)


def revise_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Re-prompt the model with the specific checks that failed."""
    enter(context, "revise")
    report = state.critic
    if report is None:  # pragma: no cover - the graph never routes here first
        return {}

    context.ledger.spend_revision()
    failing = _failing_findings(state, report)
    facts = facts_by_id(context)
    revised: list[Finding] = []

    for finding in state.findings:
        if finding.finding_id not in failing:
            revised.append(finding)
            continue

        # Emerging-theme findings come from adjudication, with their own
        # evidence and output shape. Redrafting one through the investigate
        # schema would restate a verdict as a driver finding.
        if finding.kind is not FindingKind.DRIVER or finding.category is None:
            context.ledger.note(
                f"{finding.finding_id} failed verification but cannot be revised: "
                f"only driver findings have a revision path"
            )
            revised.append(finding)
            continue

        exemplars = context.evidence.get(finding.finding_id, ())
        if not exemplars:
            context.ledger.note(
                f"{finding.finding_id} failed verification but its retrieved "
                f"evidence was not retained"
            )
            revised.append(finding)
            continue

        try:
            output = call_model(
                context,
                node="revise",
                prompt_id="revise",
                schema=InvestigateOutput,
                failures_block=_format_failures(report, finding.finding_id),
                draft_block=_format_draft(finding),
                category=finding.category,
                category_display_name=get_node(finding.category).display_name,
                week=state.brief.week,
                baseline_week=state.brief.baseline_week,
                fact_block=format_facts(
                    facts, relevant_fact_ids(state, finding.category)
                ),
                evidence_block=render_complaints(exemplars),
            )
        except BudgetExceededError as exc:
            context.ledger.note(f"revision of {finding.finding_id} stopped: {exc}")
            revised.append(finding)
            continue

        revised.append(
            to_finding(output, finding_id=finding.finding_id, category=finding.category)
        )

    log.info("revise complete: %d finding(s) redrafted", len(failing))
    return {"findings": revised, "revision": state.revision + 1}
