"""Schemas for everything the agent produces: findings, adjudications,
remediations, the verification result, and the report that carries them.

The shape enforces the invariants structurally — a claim has no field for a
number and no field for quoted text, so a fabricated figure or a misquotation
has nowhere to live.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from complaints_intelligence.inputs import FactId, SentimentSignal

#: Matches a fact placeholder written into prose, e.g. "rose to {{f_0142}}".
#: Lenient on the braces, strict on the value: models choose the right ID
#: reliably and count braces unreliably, and the ID must resolve either way.
#: Shared by the critic and the renderer so the two cannot disagree.
FACT_PLACEHOLDER_RE = re.compile(r"\{\{?(f_\d{4})\}\}?")


class FindingKind(StrEnum):
    """What a finding is about.

    There is deliberately no ``SENTIMENT`` member: sentiment trends are
    entirely figures, carried from the brief, and no node authors them.
    """

    DRIVER = "driver"
    EMERGING_THEME = "emerging_theme"


class Citation(BaseModel):
    """A pointer into a specific complaint, resolvable to source text.

    Offsets rather than copied text: the render stage pulls the quote from the
    store, so what appears in the report is necessarily what was written.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]


class Claim(BaseModel):
    """A single assertion within a finding.

    ``text`` may reference facts by placeholder but must contain no digits of
    its own; ``requires_confirmation`` marks a hypothesis, published as needing
    a named owner rather than stated as established.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    fact_refs: tuple[FactId, ...] = ()
    citations: tuple[Citation, ...] = ()
    requires_confirmation: bool = False


class Finding(BaseModel):
    """A drafted section of the report."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    kind: FindingKind
    headline: str
    claims: tuple[Claim, ...]
    #: Set on driver findings.
    category: str | None = None
    #: Set on emerging-theme findings.
    theme_id: str | None = None


class ThemeVerdict(StrEnum):
    REAL_SIGNAL = "real_signal"
    NOISE = "noise"
    INGEST_ARTEFACT = "ingest_artefact"
    DUPLICATE_OF_EXISTING = "duplicate_of_existing"


class Adjudication(BaseModel):
    """The agent's assessment of one candidate theme.

    This decides only whether a theme reaches the report as narrative;
    adopting it as a taxonomy category is a separate, human-gated act.
    """

    model_config = ConfigDict(frozen=True)

    theme_id: str
    verdict: ThemeVerdict
    rationale: str
    citations: tuple[Citation, ...] = ()
    duplicate_of_category: str | None = None


class ResolutionPrecedent(BaseModel):
    """A closed complaint whose handling may transfer to a current finding.

    Retrieval returns what is similar, which is not the same as what applies;
    a precedent that does not transfer is kept with its reason so the report
    can say what was ruled out.
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    transfers: bool
    reason: str


class Remediation(BaseModel):
    """A plain-English recommendation grounded in resolution precedent."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    recommendation: str
    precedents: tuple[ResolutionPrecedent, ...]
    citations: tuple[Citation, ...] = ()
    fact_refs: tuple[FactId, ...] = ()
    #: Advisory only; a human assigns the real owner.
    suggested_owner: str | None = None


# ---------------------------------------------------------------------------
# Verification and the report
# ---------------------------------------------------------------------------


class CriticCheck(BaseModel):
    """Result of one programmatic verification check."""

    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: str
    #: Where the failure is, for the revise loop to act on.
    offending: tuple[str, ...] = ()


class CriticReport(BaseModel):
    """Outcome of programmatic verification of a draft. No model is involved,
    which is why its verdict can be trusted to gate the render stage."""

    model_config = ConfigDict(frozen=True)

    checks: tuple[CriticCheck, ...]
    revision: int

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[CriticCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


class RunTrace(BaseModel):
    """What makes a report defensible later: the versions in force and what
    the run actually did."""

    model_config = ConfigDict(frozen=True)

    model: str
    llm_mode: str
    prompt_version: str
    taxonomy_version: str
    #: Nodes entered, in order. Reveals which revise loops fired.
    node_sequence: tuple[str, ...] = ()
    llm_calls: int = 0
    tool_calls: int = 0
    #: Non-fatal degradations: budget exhaustion, retrieval that found
    #: nothing, an adjudication the agent declined to make.
    notes: tuple[str, ...] = ()


class ReportStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    PUBLISHED = "published"


class Report(BaseModel):
    """The weekly report. The rendered Markdown is a projection of this
    object, which is what allows a historical report to be regenerated exactly
    from the store plus the pinned versions."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    week: str
    baseline_week: str
    generated_at: datetime
    #: Always a draft. The system drafts; a named human publishes, and nothing
    #: in this package performs that transition.
    status: ReportStatus = ReportStatus.DRAFT

    drivers: tuple[Finding, ...]
    #: Carried straight from the brief. Unlike every other section these are
    #: not findings, because no model produced them.
    sentiment: tuple[SentimentSignal, ...]
    emerging: tuple[Finding, ...]
    adjudications: tuple[Adjudication, ...]
    remediations: tuple[Remediation, ...]

    critic: CriticReport
    trace: RunTrace
    reviewed_by: str | None = None
