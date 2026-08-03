"""The complaint taxonomy, held as versioned data rather than code.

In the full design this lives in a taxonomy store: node definitions,
inclusion/exclusion criteria, exemplars, validity dates, and old->new mapping
tables, never mutated in place. That is what guarantees month-to-month
comparability. Here it is a frozen module-level structure standing in for
version ``v4.2`` of that store.

Twelve categories rather than the ~40 of the real problem: the fixtures must
stay small enough for a human to read and follow.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from complaints_intelligence.config import TAXONOMY_VERSION


class TaxonomyNode(BaseModel):
    """One category in the taxonomy.

    ``inclusion`` and ``exclusion`` are carried because they are what makes a
    category auditable: a reviewer asking "why was this complaint counted
    here" needs a written criterion, not a classifier's opinion.
    """

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
        exclusion="Card purchases declined at point of sale (see card_declines).",
    ),
    TaxonomyNode(
        category="card_fraud_handling",
        display_name="Handling of reported card fraud",
        product="card",
        inclusion="Dissatisfaction with investigation or refund of disputed items.",
        exclusion="The fraud itself where no service failing is alleged.",
    ),
    TaxonomyNode(
        category="card_declines",
        display_name="Card declined at point of sale",
        product="card",
        inclusion="Card refused despite available funds and no block advised.",
        exclusion="Declines the customer accepts were correctly applied.",
    ),
    TaxonomyNode(
        category="mortgage_arrears_support",
        display_name="Support during mortgage arrears",
        product="mortgage",
        inclusion="Forbearance, affordability or arrears-handling concerns.",
        exclusion="Disputes about the original lending decision.",
    ),
    TaxonomyNode(
        category="overdraft_fees",
        display_name="Overdraft fees and charges",
        product="current_account",
        inclusion="Unexpected, unexplained or disputed overdraft charges.",
        exclusion="Refusal of a fee waiver request (separate process).",
    ),
    TaxonomyNode(
        category="app_login",
        display_name="Mobile app access and login",
        product="digital",
        inclusion="Unable to authenticate, register a device, or access the app.",
        exclusion="App features working as designed but disliked.",
    ),
    TaxonomyNode(
        category="branch_closure",
        display_name="Branch closure and reduced hours",
        product="branch",
        inclusion="Loss of, or reduced, in-person access.",
        exclusion="Service quality within an open branch.",
    ),
    TaxonomyNode(
        category="complaint_handling_delay",
        display_name="Delay in handling a prior complaint",
        product="service",
        inclusion="The firm's handling of an earlier complaint is itself the subject.",
        exclusion="First-instance complaints about any other matter.",
    ),
    TaxonomyNode(
        category="savings_rate_change",
        display_name="Savings rate changes and notice",
        product="savings",
        inclusion="Rate reduction, notice period or communication of a change.",
        exclusion="General dissatisfaction with market rates.",
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
        category="statement_errors",
        display_name="Statement and balance errors",
        product="current_account",
        inclusion="Statements missing, inaccurate or showing wrong balances.",
        exclusion="Correct statements the customer misread.",
    ),
)

CATEGORIES: tuple[str, ...] = tuple(node.category for node in TAXONOMY)

_BY_CATEGORY = {node.category: node for node in TAXONOMY}


def get_node(category: str) -> TaxonomyNode:
    """Look up a category, raising on an unknown one.

    Unknown categories are a bug, not a runtime condition: the classifier
    operates over a closed set and everything outside it abstains.
    """
    try:
        return _BY_CATEGORY[category]
    except KeyError as exc:
        msg = f"unknown category {category!r} in taxonomy {TAXONOMY_VERSION}"
        raise KeyError(msg) from exc


def display_name(category: str) -> str:
    """Plain-English label for a category, for use in the report."""
    return get_node(category).display_name
