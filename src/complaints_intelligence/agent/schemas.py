"""Schemas the model writes into.

Separate from ``outputs`` on purpose: these are the *model's* contract, so
fields it must not control — finding identifiers, resolved values, pinned
versions — have nowhere to arrive from, and the mapping between the two is an
explicit, reviewable step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DraftCitation(BaseModel):
    """A pointer into a complaint, as written by the model. Offsets are checked
    against the store by the critic, the only place that can tell."""

    complaint_id: str = Field(description="ID of the complaint being cited.")
    start: int = Field(description="Start character offset, inclusive.")
    end: int = Field(description="End character offset, exclusive.")


class DraftClaim(BaseModel):
    """One assertion within a drafted finding."""

    text: str = Field(
        description=(
            "The claim in plain English. Must contain no digits. Reference "
            "figures as fact IDs in double braces, e.g. {{f_0142}}."
        )
    )
    fact_refs: list[str] = Field(
        default_factory=list,
        description="Fact IDs referenced in the text, e.g. ['f_0142'].",
    )
    citations: list[DraftCitation] = Field(
        default_factory=list,
        description="At least two complaint citations supporting this claim.",
    )


class InvestigateOutput(BaseModel):
    """A drafted finding for one category.

    ``hypotheses`` gives a causal belief somewhere legitimate to go: without
    it, a model that has spotted a plausible cause either suppresses a useful
    observation or smuggles it into a claim.
    """

    headline: str = Field(description="One line summarising the finding.")
    claims: list[DraftClaim] = Field(default_factory=list)
    hypotheses: list[str] = Field(
        default_factory=list,
        description=(
            "Causal explanations you believe plausible. Published as requiring "
            "confirmation by a named owner, never as findings."
        ),
    )


class AdjudicateOutput(BaseModel):
    """A verdict on one candidate theme."""

    verdict: str = Field(
        description=(
            "One of: real_signal, noise, ingest_artefact, duplicate_of_existing."
        )
    )
    rationale: str = Field(
        description="Reasoning in terms of the evidence actually seen. No digits."
    )
    citations: list[DraftCitation] = Field(default_factory=list)
    duplicate_of_category: str | None = Field(
        default=None, description="Set only when the verdict is duplicate_of_existing."
    )
    headline: str = Field(
        default="", description="One line describing the theme, for the report."
    )


class DraftPrecedent(BaseModel):
    """The model's assessment of whether one precedent transfers."""

    complaint_id: str
    transfers: bool
    reason: str = Field(description="One sentence justifying the assessment.")


class RemediateOutput(BaseModel):
    """A remediation recommendation grounded in resolution precedent."""

    recommendation: str = Field(
        description=(
            "Plain English: what should be done, by whom. No digits; use fact "
            "IDs in double braces where a figure belongs."
        )
    )
    precedents: list[DraftPrecedent] = Field(default_factory=list)
    citations: list[DraftCitation] = Field(default_factory=list)
    fact_refs: list[str] = Field(default_factory=list)
    suggested_owner: str | None = Field(
        default=None, description="Advisory only; a human assigns the real owner."
    )
