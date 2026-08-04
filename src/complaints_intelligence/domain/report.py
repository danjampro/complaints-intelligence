"""The report object: versioned, immutable, fact-referenced.

The report is a record. Published versions must be immutable and exactly
reconstructable, so this object pins prompt, model and taxonomy versions and
carries the full run trace alongside the content.

``status`` moves draft -> reviewed -> published by a named human. The system
drafts; a person publishes. Nothing in this package performs that transition.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from complaints_intelligence.domain.brief import SentimentSignal
from complaints_intelligence.domain.finding import Adjudication, Finding, Remediation
from complaints_intelligence.domain.trace import RunTrace


class ReportStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    PUBLISHED = "published"


class CriticCheck(BaseModel):
    """Result of one programmatic verification check."""

    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: str
    #: Where the failure is, for the revise loop to act on.
    offending: tuple[str, ...] = ()


class CriticReport(BaseModel):
    """Outcome of programmatic verification of a draft.

    No model is involved. These are assertions about structure and provenance,
    not judgements about quality, which is precisely why they can be trusted
    to gate the render stage.
    """

    model_config = ConfigDict(frozen=True)

    checks: tuple[CriticCheck, ...]
    revision: int

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[CriticCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


class Report(BaseModel):
    """The immutable weekly report.

    Content is held as findings referencing fact IDs and complaint offsets.
    The rendered Markdown is a projection of this object, not the other way
    round — which is what allows any historical report to be regenerated
    exactly from the store plus the pinned versions.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    week: str
    baseline_week: str
    generated_at: datetime
    status: ReportStatus = ReportStatus.DRAFT

    drivers: tuple[Finding, ...]
    #: Within-channel sentiment shifts, carried straight from the metrics
    #: brief. Unlike every other section these are not findings, because no
    #: model produced them: a sentiment trend is entirely figures, and figures
    #: are the one thing the model may never author (invariant 1). Carrying
    #: them on the report rather than reading the brief at render time is what
    #: keeps the Markdown a projection of this object.
    sentiment: tuple[SentimentSignal, ...]
    emerging: tuple[Finding, ...]
    adjudications: tuple[Adjudication, ...]
    remediations: tuple[Remediation, ...]

    critic: CriticReport
    trace: RunTrace

    #: Populated at sign-off. Absent on a draft.
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
