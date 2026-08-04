"""The ``critic`` and ``revise`` nodes.

``critic`` runs the programmatic verification suite. No model is involved — it
is regular expressions and lookups against the store, which is why its verdict
can be trusted to gate rendering.

``revise`` re-prompts the model with the specific failures. It is bounded at
two rounds. If the draft still fails, the run does not render a report it
cannot stand behind: it fails, and says which check failed and where.
"""

from __future__ import annotations

from typing import Any

from complaints_intelligence.agent.nodes.common import call_model, enter, format_facts
from complaints_intelligence.agent.nodes.investigate import (
    _to_finding,
    relevant_fact_ids,
)
from complaints_intelligence.agent.schemas import InvestigateOutput
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.agent.untrusted import render_complaints
from complaints_intelligence.critic.verify import verify
from complaints_intelligence.domain.finding import Finding, FindingKind
from complaints_intelligence.domain.report import CriticReport
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.render.spans import clamp_and_snap
from complaints_intelligence.synth.taxonomy import get_node

log = get_logger(__name__)

CRITIC_NODE = "critic"
REVISE_NODE = "revise"


def _rendered_texts(state: RunState, context: RunContext) -> list[tuple[str, str]]:
    """Claim text plus the source spans citations will resolve to.

    The PII scan runs over both. A quotation pulled from the store can carry
    an identifier redaction missed, and scanning only the model's own prose
    would inspect the part of the report least likely to contain any.

    The span is resolved with the renderer's own arithmetic rather than a copy
    of it. The renderer widens a citation to word boundaries before printing,
    so a narrower scan here would let it print an identifier the check never
    saw — a citation ending mid-digit-run widens into a whole account number.
    """
    texts: list[tuple[str, str]] = []
    for finding in state.findings:
        for claim in finding.claims:
            texts.append((finding.finding_id, claim.text))
            for citation in claim.citations:
                try:
                    complaint = context.store.get_complaint(citation.complaint_id)
                except KeyError:
                    continue
                start, end = clamp_and_snap(
                    complaint.text, citation.start, citation.end
                )
                texts.append(
                    (
                        f"{finding.finding_id}/{citation.complaint_id}",
                        complaint.text[start:end],
                    )
                )
    for remediation in state.remediations:
        texts.append((remediation.finding_id, remediation.recommendation))
    return texts


def critic_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Verify the draft."""
    enter(context, CRITIC_NODE)
    report = verify(
        state.findings,
        facts=context.store,
        complaints=context.store,
        thresholds=context.settings.critic,
        revision=state.revision,
        rendered_texts=_rendered_texts(state, context),
    )
    return {"critic": report}


def _failing_findings(state: RunState, report: CriticReport) -> set[str]:
    """Finding IDs named in at least one failure.

    Only these are re-prompted. Re-drafting a finding that passed would spend
    budget to risk breaking something that works.
    """
    ids = {f.finding_id for f in state.findings}
    failing: set[str] = set()
    for check in report.failures:
        for offence in check.offending:
            for finding_id in ids:
                if offence.startswith(f"{finding_id}:") or offence.startswith(
                    f"{finding_id}/"
                ):
                    failing.add(finding_id)
    return failing


def _format_failures(report: CriticReport, finding_id: str) -> str:
    lines = []
    for check in report.failures:
        relevant = [
            o
            for o in check.offending
            if o.startswith(f"{finding_id}:") or o.startswith(f"{finding_id}/")
        ]
        if relevant:
            lines.append(f"- **{check.name}**: {check.detail}")
            lines.extend(f"  - {o}" for o in relevant)
    return "\n".join(lines) if lines else "- (no failures attributed to this finding)"


def _format_draft(finding: Finding) -> str:
    lines = [f"Headline: {finding.headline}", "", "Claims:"]
    for index, claim in enumerate(finding.claims, start=1):
        citations = ", ".join(
            f"{c.complaint_id}[{c.start}:{c.end}]" for c in claim.citations
        )
        lines.append(f"{index}. {claim.text}")
        lines.append(f"   fact_refs: {list(claim.fact_refs)}")
        lines.append(f"   citations: {citations or '(none)'}")
    return "\n".join(lines)


def revise_node(state: RunState, context: RunContext) -> dict[str, Any]:
    """Re-prompt the model with the specific checks that failed."""
    enter(context, REVISE_NODE)
    report = state.critic
    if report is None:  # pragma: no cover - the graph never routes here first
        return {}

    context.ledger.spend_revision()
    failing = _failing_findings(state, report)
    facts = {f.id: f for f in context.store.all_facts()}
    revised: list[Finding] = []

    for finding in state.findings:
        if finding.finding_id not in failing:
            revised.append(finding)
            continue

        # Emerging-theme findings come from adjudication, which has its own
        # evidence and its own output shape. Re-drafting one through the
        # investigate schema would restate a verdict as a driver finding, so
        # it is left alone — and the run records that the loop could not help,
        # rather than looping twice and failing without explanation.
        if finding.kind is not FindingKind.DRIVER or finding.category is None:
            context.ledger.note(
                f"{finding.finding_id} failed verification but cannot be "
                f"revised: only driver findings have a revision path"
            )
            revised.append(finding)
            continue

        exemplars = context.evidence.get(finding.finding_id, ())
        if not exemplars:
            context.ledger.note(
                f"{finding.finding_id} failed verification but cannot be "
                f"revised: its retrieved evidence was not retained"
            )
            revised.append(finding)
            continue

        node_definition = get_node(finding.category)
        try:
            output = call_model(
                context,
                node=REVISE_NODE,
                prompt_id="revise",
                schema=InvestigateOutput,
                failures_block=_format_failures(report, finding.finding_id),
                draft_block=_format_draft(finding),
                category=finding.category,
                category_display_name=node_definition.display_name,
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
            _to_finding(
                output,
                finding_id=finding.finding_id,
                category=finding.category,
            )
        )

    log.info("revise_complete", revised=len(failing), revision=state.revision + 1)
    return {"findings": revised, "revision": state.revision + 1}
