"""The complaint taxonomy, held as versioned data rather than code.

In the full design this is a taxonomy store with validity dates and old->new
mapping tables, never mutated in place; here it stands in for version v4.2.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TaxonomyNode(BaseModel):
    """One category. ``inclusion`` and ``exclusion`` are what make a category
    auditable, and the retrieval query for a finding is built from them."""

    model_config = ConfigDict(frozen=True)

    category: str
    display_name: str
    product: str
    inclusion: str
    exclusion: str


TAXONOMY: tuple[TaxonomyNode, ...] = (
    TaxonomyNode(
        category="payments_failed",
        display_name="Failed or delayed payments",
        product="current_account",
        inclusion="Outbound payment rejected, delayed or duplicated.",
        exclusion="Card purchases declined at point of sale.",
    ),
    TaxonomyNode(
        category="overdraft_fees",
        display_name="Overdraft fees and charges",
        product="current_account",
        inclusion="Unexpected, unexplained or disputed overdraft charges.",
        exclusion="Refusal of a fee waiver request, which is a separate process.",
    ),
    TaxonomyNode(
        category="direct_debit_errors",
        display_name="Direct debit set-up and cancellation errors",
        product="current_account",
        inclusion="Mandate taken, cancelled or amended incorrectly.",
        exclusion="Disputes with the originating merchant only.",
    ),
    TaxonomyNode(
        category="vulnerable_customer_support",
        display_name="Support for customers in vulnerable circumstances",
        product="service",
        inclusion="Reasonable adjustments not made, or disclosed needs ignored.",
        exclusion="Cases where no vulnerability was disclosed to the firm.",
    ),
    TaxonomyNode(
        category="branch_closure",
        display_name="Branch closure and reduced hours",
        product="branch",
        inclusion="Loss of, or reduced, in-person access.",
        exclusion="Service quality within an open branch.",
    ),
    TaxonomyNode(
        category="statement_errors",
        display_name="Statement and balance errors",
        product="current_account",
        inclusion="Statements missing, inaccurate or showing wrong balances.",
        exclusion="Correct statements the customer misread.",
    ),
)

_BY_CATEGORY = {node.category: node for node in TAXONOMY}


def get_node(category: str) -> TaxonomyNode:
    """Look up a category, raising on an unknown one — the classifier operates
    over a closed set, so anything outside it is a bug."""
    try:
        return _BY_CATEGORY[category]
    except KeyError as exc:
        msg = f"unknown category {category!r}"
        raise KeyError(msg) from exc


def display_name(category: str) -> str:
    """Plain-English label for a category, for use in the report."""
    return get_node(category).display_name
