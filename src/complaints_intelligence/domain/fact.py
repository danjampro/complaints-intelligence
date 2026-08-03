"""Facts: the trust boundary of the system.

Everything below the fact store is deterministic and reproducible; everything
above it is generative. A fact is a typed value with provenance, emitted by
the metrics layer before any model is invoked.

Report claims reference fact IDs rather than literal values, so figures are
substituted at render time and cannot be fabricated by a language model
(invariant 1).

Facts are written once per run and never mutated. A taxonomy re-projection
produces a new run, not an edit — otherwise a published report stops
reconciling with the store it cites.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

#: Fact identifiers are ``f_`` plus four digits, e.g. ``f_0142``.
FACT_ID_PATTERN = r"^f_\d{4}$"

FactId = Annotated[str, Field(pattern=FACT_ID_PATTERN)]


class FactUnit(StrEnum):
    """How a fact's value should be read and formatted.

    Carried on the fact rather than inferred at render time, so a proportion
    can never be printed as a count.
    """

    COMPLAINTS = "complaints"
    PROPORTION = "proportion"
    SENTIMENT_INDEX = "sentiment_index"
    DAYS = "days"
    GBP = "gbp"
    COUNT = "count"


class Provenance(BaseModel):
    """How a fact was derived: the view queried and the parameters used.

    Enough to re-run the derivation and get the same value. This is what makes
    a figure re-derivable eighteen months later rather than merely recorded.
    """

    model_config = ConfigDict(frozen=True)

    view: str
    params: dict[str, str | int | float]


class Fact(BaseModel):
    """A single precomputed figure with its provenance.

    Example::

        Fact(
            id="f_0142",
            run_id="2026-W31",
            label="payments_failed · count · 2026-W31",
            value=142,
            unit=FactUnit.COMPLAINTS,
            taxonomy_version="v4.2",
            provenance=Provenance(
                view="v_weekly_category_counts",
                params={"category": "payments_failed", "week": "2026-W31"},
            ),
        )
    """

    model_config = ConfigDict(frozen=True)

    id: FactId
    run_id: str
    #: Human-readable identification of what this measures. Shown to the model
    #: so it can choose the right fact; never used as the rendered value.
    label: str
    value: float
    unit: FactUnit
    taxonomy_version: str
    provenance: Provenance

    #: Optional dimensions, for facts scoped to a category or channel.
    category: str | None = None
    channel: str | None = None
    week: str | None = None

    def render(self) -> str:
        """Format the value for the report.

        Formatting lives with the fact rather than in the template so a figure
        is presented identically wherever it appears.
        """
        match self.unit:
            case FactUnit.PROPORTION:
                return f"{self.value * 100:.1f}%"
            case FactUnit.SENTIMENT_INDEX:
                return f"{self.value:+.2f}"
            case FactUnit.GBP:
                return f"£{self.value:,.0f}"
            case FactUnit.DAYS:
                return f"{self.value:.1f} days"
            case _:
                return f"{self.value:,.0f}"
