"""Exception hierarchy.

One root so callers can catch everything this package raises, and specific
subclasses where the caller is expected to branch on the failure mode.
"""

from __future__ import annotations


class ComplaintsIntelligenceError(Exception):
    """Root of every exception raised by this package."""


class BudgetExceededError(ComplaintsIntelligenceError):
    """A bounded resource on the agent run was exhausted.

    Raised by the budget wrapper (``agent.budgets``) rather than by nodes. The
    graph catches it and terminates with a partial report plus a recorded
    reason: invariant 4 requires the agent to be bounded, and a bound that
    crashes the run is not a usable bound.
    """


class CassetteMissError(ComplaintsIntelligenceError):
    """The replay LLM client had no recording for a prompt.

    Deliberately loud. A silent fallback to a live call would break the
    offline guarantee (invariant 5); a silent fallback to a stub response
    would make the demo a fiction.
    """


class ProvenanceError(ComplaintsIntelligenceError):
    """A claim referenced a fact or citation that does not resolve.

    Invariants 1 and 2 are assertions, not metrics. If the render stage cannot
    resolve a fact ID to a stored value, or a citation to its source span, the
    run fails rather than emitting an unsupported figure.
    """


class ToolContractError(ComplaintsIntelligenceError):
    """A tool was called with arguments outside its declared contract.

    The agent reaches the store only through parameterised, allowlisted views.
    This is what a free-form SQL attempt looks like when it hits the wall.
    """
