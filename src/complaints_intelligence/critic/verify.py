"""Running the full verification suite over a draft."""

from __future__ import annotations

from collections.abc import Sequence

from complaints_intelligence.config import CriticThresholds
from complaints_intelligence.critic import checks
from complaints_intelligence.domain.finding import Finding
from complaints_intelligence.domain.report import CriticReport
from complaints_intelligence.logging import get_logger
from complaints_intelligence.store.protocols import ComplaintRepository, FactStore

log = get_logger(__name__)


def verify(
    findings: Sequence[Finding],
    *,
    facts: FactStore,
    complaints: ComplaintRepository,
    thresholds: CriticThresholds,
    revision: int,
    rendered_texts: Sequence[tuple[str, str]] = (),
) -> CriticReport:
    """Run every check and return the combined report.

    All checks run even after the first failure. A revise loop that is told
    about one problem at a time takes as many rounds as there are problems,
    and the revision budget is two.

    ``rendered_texts`` carries resolved output — including quotations pulled
    from the store — for the PII scan. Passing nothing means the scan covers
    only the model's own words, which is the weaker check.
    """
    results = (
        checks.check_facts_resolve(findings, facts),
        checks.check_no_literal_numbers(findings),
        checks.check_citations_present(findings, thresholds),
        checks.check_citations_resolve(findings, complaints),
        checks.check_no_causal_language(findings),
        checks.check_no_pii(
            list(rendered_texts)
            or [(f.finding_id, c.text) for f in findings for c in f.claims]
        ),
        checks.check_no_unexplained_acronyms(findings),
    )

    report = CriticReport(checks=results, revision=revision)
    log.info(
        "critic_run",
        revision=revision,
        passed=report.passed,
        failed=[c.name for c in report.failures],
    )
    return report
