"""Schemas the model writes into.

Separate from ``domain.finding`` on purpose. These are the *model's* output
contract; the domain objects are what the system commits to. Keeping them
apart means fields the model must not control — finding identifiers, resolved
values, the run's pinned versions — have nowhere to arrive from, and the
mapping between the two is an explicit, reviewable step.

Deliberately plain: lists rather than tuples, no regex constraints, no
validators. These are handed to the provider as a response schema, and a
constraint expressed here that the provider silently ignores would be a
guarantee that is not enforced. Everything that must actually hold is checked
by the critic, against the store.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DraftCitation(BaseModel):
    """A pointer into a complaint, as written by the model.

    Offsets are unvalidated here. They are checked against the store by the
    critic, which is the only place that can tell whether they resolve.
    """

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


class PlannedInvestigation(BaseModel):
    """One item the agent intends to investigate."""

    target: str = Field(
        description="Category name or candidate theme ID, e.g. 'CT-007'."
    )
    kind: str = Field(description="Either 'category' or 'candidate_theme'.")
    reason: str = Field(description="One sentence on why this merits attention.")


class SkippedNote(BaseModel):
    """Something in the brief the agent chose not to investigate."""

    target: str
    reason: str


class PlanOutput(BaseModel):
    """Result of the plan node."""

    investigations: list[PlannedInvestigation] = Field(default_factory=list)
    skipped: list[SkippedNote] = Field(default_factory=list)


class InvestigateOutput(BaseModel):
    """A drafted finding for one category.

    ``hypotheses`` exists so the model has somewhere legitimate to put a
    causal belief. Without it, a model that has spotted a plausible cause
    either suppresses a useful observation or smuggles it into a claim as
    causal language. Here it is captured and published as requiring
    confirmation by a named owner, which is what the design calls for.
    """

    headline: str = Field(description="One line summarising the finding.")
    claims: list[DraftClaim] = Field(default_factory=list)
    hypotheses: list[str] = Field(
        default_factory=list,
        description=(
            "Causal explanations you believe plausible. Published as "
            "requiring confirmation, never as findings."
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
        description="Reasoning in terms of the evidence actually seen."
    )
    citations: list[DraftCitation] = Field(default_factory=list)
    duplicate_of_category: str | None = Field(
        default=None,
        description="Set only when the verdict is duplicate_of_existing.",
    )
    headline: str = Field(
        default="",
        description="One line describing the theme, for the report section.",
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
            "Plain English: what should be done, by whom. No digits; use "
            "fact IDs in double braces where a figure belongs."
        )
    )
    precedents: list[DraftPrecedent] = Field(default_factory=list)
    citations: list[DraftCitation] = Field(default_factory=list)
    fact_refs: list[str] = Field(default_factory=list)
    suggested_owner: str | None = Field(
        default=None, description="Advisory only; a human assigns the real owner."
    )
