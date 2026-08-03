"""The bounded agent graph.

    plan -> investigate -> adjudicate -> remediate -> critic -> revise
                                              ^                    |
                                              +--------------------+

Read-only tools, no write access, no network egress, budgeted steps. The
routing decision after ``critic`` is the only conditional edge: pass, or
revise if the budget allows.

``render`` is deliberately **not** a node. Rendering is deterministic
templating with no model involvement, so it runs after the graph completes,
against the verified state. Putting it in the graph would place it in reach of
a revision loop, and the one stage that must never vary is the one that
substitutes real figures into prose.

Context — store, tools, client — is bound into each node with a closure rather
than carried on the state. LangGraph serialises state between nodes; a DuckDB
connection does not serialise, and a graph whose state cannot be checkpointed
is a graph that cannot be resumed or inspected.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

from langgraph.graph import END, StateGraph

from complaints_intelligence.agent.nodes.adjudicate import adjudicate_node
from complaints_intelligence.agent.nodes.criticise import (
    critic_node,
    revise_node,
)
from complaints_intelligence.agent.nodes.investigate import investigate_node
from complaints_intelligence.agent.nodes.planner import plan_node
from complaints_intelligence.agent.nodes.remediate import remediate_node
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.errors import BudgetExceededError
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)

NodeFn = Callable[[RunState, RunContext], dict[str, Any]]


class BoundNode(Protocol):
    """A node with its context already bound.

    A callback protocol rather than a ``Callable`` alias, because LangGraph's
    node type requires the state parameter to be *named* ``state`` and
    ``Callable[[RunState], ...]`` declares it positional-only. Matching the
    shape here keeps ``add_node`` type-checked instead of suppressed.
    """

    def __call__(self, state: RunState) -> dict[str, Any]: ...


class RouterFn(Protocol):
    """A conditional-edge router, same naming requirement as ``BoundNode``."""

    def __call__(self, state: RunState) -> Literal["revise", "__end__"]: ...


def _bind(node: NodeFn, context: RunContext) -> BoundNode:
    """Bind a node to its context and contain budget exhaustion.

    A budget is a bound on the run, not a way to fail it. If a node exhausts
    the budget the run keeps whatever it has produced, records why it stopped,
    and continues to the critic — a partial report that says it is partial is
    more useful than a traceback.
    """

    def run(state: RunState) -> dict[str, Any]:
        try:
            return node(state, context)
        except BudgetExceededError as exc:
            context.ledger.note(str(exc))
            return {"notes": [*state.notes, str(exc)]}

    return run


def _route_after_critic(context: RunContext) -> RouterFn:
    """Decide whether to revise or finish.

    Two conditions, both hard: the critic must have failed, and the revision
    budget must allow another round. A run that exhausts its revisions with
    failures outstanding ends here and is caught by the caller — the graph
    does not render an unverified report, and it does not loop forever
    trying not to.
    """

    def route(state: RunState) -> Literal["revise", "__end__"]:
        report = state.critic
        if report is None or report.passed:
            return "__end__"
        if not context.ledger.may_revise():
            context.ledger.note(
                f"revision budget exhausted with "
                f"{len(report.failures)} check(s) still failing"
            )
            return "__end__"
        return "revise"

    return route


def build_graph(context: RunContext) -> Any:
    """Compile the agent graph for one run."""
    graph: StateGraph[RunState] = StateGraph(RunState)

    graph.add_node("plan", _bind(plan_node, context))
    graph.add_node("investigate", _bind(investigate_node, context))
    graph.add_node("adjudicate", _bind(adjudicate_node, context))
    graph.add_node("remediate", _bind(remediate_node, context))
    graph.add_node("critic", _bind(critic_node, context))
    graph.add_node("revise", _bind(revise_node, context))

    graph.set_entry_point("plan")
    graph.add_edge("plan", "investigate")
    graph.add_edge("investigate", "adjudicate")
    graph.add_edge("adjudicate", "remediate")
    graph.add_edge("remediate", "critic")
    graph.add_conditional_edges(
        "critic",
        _route_after_critic(context),
        {"revise": "revise", "__end__": END},
    )
    # A revision changes the findings, so they must be re-verified. This edge
    # is what makes the loop a loop; the budget check in the router is what
    # makes it terminate.
    graph.add_edge("revise", "critic")

    return graph.compile()


def run_graph(context: RunContext, initial: RunState) -> RunState:
    """Execute the graph and return the final state."""
    compiled = build_graph(context)
    # `recursion_limit` is a backstop under the budget ledger, not the primary
    # bound. Nodes plus two revision rounds is a short path; anything longer
    # means a routing bug, and failing loudly beats spinning.
    result = compiled.invoke(initial, {"recursion_limit": 25})
    final = RunState.model_validate(result)

    log.info(
        "graph_complete",
        nodes=len(context.node_sequence),
        findings=len(final.findings),
        adjudications=len(final.adjudications),
        remediations=len(final.remediations),
        passed=final.critic.passed if final.critic else None,
        **context.ledger.summary(),
    )
    return final
