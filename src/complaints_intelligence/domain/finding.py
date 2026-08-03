"""Findings: what the model is allowed to write.

These are the schemas model output is parsed into. Nothing is scraped from
text. The shape enforces the invariants structurally:

- A claim carries ``fact_refs`` (IDs) and ``citations`` (complaint ID plus
  offsets). It has no field for a number and no field for quoted text, so a
  fabricated figure or a misquotation has nowhere to live.
- Values and quotes are resolved from the store at render time.

The model chooses *which* fact to cite and writes the prose around it. It
never types a figure.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from complaints_intelligence.domain.fact import FactId

#: Placeholder syntax the model writes into prose where a figure belongs,
#: e.g. "volumes rose to {{f_0142}} complaints". Resolved at render time.
FACT_PLACEHOLDER = "{{{{{fact_id}}}}}"


class FindingKind(StrEnum):
    DRIVER = "driver"
    SENTIMENT = "sentiment"
    EMERGING_THEME = "emerging_theme"
    REMEDIATION = "remediation"


class Citation(BaseModel):
    """A pointer into a specific complaint, resolvable to source text.

    Offsets rather than copied text: the render stage pulls the quote from the
    store, so what appears in the report is necessarily what the customer
    wrote (invariant 2).
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]


class Claim(BaseModel):
    """A single assertion within a finding.

    ``text`` may reference facts by placeholder but must contain no digits of
    its own — the critic enforces this. ``requires_confirmation`` marks a
    causal hypothesis, which is emitted as needing a named owner rather than
    stated as established.
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

    #: Set on driver and sentiment findings.
    category: str | None = None
    #: Set on emerging-theme findings.
    theme_id: str | None = None


class ThemeVerdict(StrEnum):
    """The adjudication outcome for a candidate theme."""

    REAL_SIGNAL = "real_signal"
    NOISE = "noise"
    INGEST_ARTEFACT = "ingest_artefact"
    DUPLICATE_OF_EXISTING = "duplicate_of_existing"


class Adjudication(BaseModel):
    """The model's assessment of one candidate theme.

    Reporting an emerging theme and adopting it as a category are different
    acts. This decides only whether the theme reaches the report as narrative.
    Adoption is structural, slow and human-gated.
    """

    model_config = ConfigDict(frozen=True)

    theme_id: str
    verdict: ThemeVerdict
    rationale: str
    citations: tuple[Citation, ...] = ()
    #: Set where the verdict is ``DUPLICATE_OF_EXISTING``.
    duplicate_of_category: str | None = None


class ResolutionPrecedent(BaseModel):
    """A closed complaint whose handling may transfer to a current finding.

    ``transfers`` is the point of the assessment step: retrieval returns
    what is similar, which is not the same as what is applicable. A precedent
    that does not transfer is retained with its reason rather than discarded,
    so the remediation section can say what was ruled out.
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
    #: Owner suggested by the model. Advisory; a human assigns the real one.
    suggested_owner: str | None = None
