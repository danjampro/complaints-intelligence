"""The bounded agent graph.

    investigate -> adjudicate -> remediate -> critic -> revise
                                                ^          |
                                                +----------+

Rendering is deliberately **not** a node. It is deterministic templating with
no model involvement, so it runs after the graph against verified state — the
one stage that must never vary is the one that substitutes real figures into
prose, and putting it in the graph would place it inside a revision loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal, Protocol

from langgraph.graph import END, StateGraph

from complaints_intelligence.agent.nodes import (
    adjudicate_node,
    investigate_node,
    remediate_node,
)
from complaints_intelligence.agent.state import (
    BudgetExceededError,
    RunContext,
    RunState,
)
from complaints_intelligence.agent.verify import critic_node, revise_node

log = logging.getLogger(__name__)

NodeFn = Callable[[RunState, RunContext], dict[str, Any]]


class BoundNode(Protocol):
    """A node with its context bound. A callback protocol rather than a
    ``Callable`` alias, because LangGraph requires the parameter to be *named*
    ``state`` and a ``Callable`` alias declares it positional-only."""

    def __call__(self, state: RunState) -> dict[str, Any]: ...


class RouterFn(Protocol):
    """A conditional-edge router, with the same naming requirement."""

    def __call__(self, state: RunState) -> Literal["revise", "__end__"]: ...


def _bind(node: NodeFn, context: RunContext) -> BoundNode:
    """Bind a node to its context and contain budget exhaustion.

    A budget is a bound on the run, not a way to fail it: an exhausted node
    keeps what it produced, records why it stopped, and continues to the critic.
    """

    def run(state: RunState) -> dict[str, Any]:
        try:
            return node(state, context)
        except BudgetExceededError as exc:
            context.ledger.note(str(exc))
            return {}

    return run


def _route_after_critic(context: RunContext) -> RouterFn:
    """Revise or finish. Two hard conditions: the critic must have failed, and
    the revision budget must allow another round."""

    def route(state: RunState) -> Literal["revise", "__end__"]:
        report = state.critic
        if report is None or report.passed:
            return "__end__"
        if not context.ledger.may_revise():
            context.ledger.note(
                f"revision budget exhausted with {len(report.failures)} "
                f"check(s) still failing"
            )
            return "__end__"
        return "revise"

    return route


def run_graph(context: RunContext, initial: RunState) -> RunState:
    """Compile and execute the graph, returning the final state."""
    graph: StateGraph[RunState] = StateGraph(RunState)
    graph.add_node("investigate", _bind(investigate_node, context))
    graph.add_node("adjudicate", _bind(adjudicate_node, context))
    graph.add_node("remediate", _bind(remediate_node, context))
    graph.add_node("critic", _bind(critic_node, context))
    graph.add_node("revise", _bind(revise_node, context))

    graph.set_entry_point("investigate")
    graph.add_edge("investigate", "adjudicate")
    graph.add_edge("adjudicate", "remediate")
    graph.add_edge("remediate", "critic")
    graph.add_conditional_edges(
        "critic", _route_after_critic(context), {"revise": "revise", "__end__": END}
    )
    # A revision changes the findings, so they must be re-verified. This edge
    # makes the loop a loop; the budget check in the router makes it terminate.
    graph.add_edge("revise", "critic")

    # A backstop under the budget ledger, not the primary bound: four nodes
    # plus two revision rounds is a short path, and anything longer is a
    # routing bug.
    result = graph.compile().invoke(initial, {"recursion_limit": 25})
    final = RunState.model_validate(result)

    log.info(
        "graph complete: %d findings, %d adjudications, %d remediations, passed=%s",
        len(final.findings),
        len(final.adjudications),
        len(final.remediations),
        final.critic.passed if final.critic else None,
    )
    return final
