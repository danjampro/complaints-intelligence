# ADR-0008 — LangGraph as the graph runtime

**Status:** Accepted

## Context

ADR-0005 settles that the agent is a bounded graph. This decides what runs it.

## Decision

LangGraph `StateGraph` over a Pydantic `RunState`.

Context — store, tools, LLM client — is bound into each node by closure rather
than carried on the state. LangGraph serialises state between nodes; a DuckDB
connection does not serialise, and a state that cannot be checkpointed cannot
be resumed or inspected.

## Consequences

The graph declaration reads as the diagram in the architecture document, which
is the main benefit: a reviewer comparing §8 to `agent/graph.py` sees the same
thing twice. Checkpointing, streaming and interrupt-for-human-approval are
available without rework — the last matters, because sign-off is a human gate
in the full design.

**Costs, encountered rather than anticipated.** LangGraph's node type is a
callback `Protocol` requiring the state parameter be *named* `state`, so a
`Callable[[RunState], ...]` alias does not satisfy it — `Callable` declares
positional-only parameters. The fix is to declare matching callback protocols
(`BoundNode`, `RouterFn` in `agent/graph.py`), which keeps `add_node`
type-checked under `mypy --strict` rather than suppressed. Worth recording
because the obvious workaround is a `# type: ignore` on every `add_node` call,
and that would discard real checking.

`langgraph` also pulls `langchain-core`, which is a larger dependency than the
graph logic itself warrants.

## Alternatives rejected

**Hand-rolled typed graph.** ~150 lines: a node registry, explicit budgets, a
bounded loop. Genuinely tempting — it would type-check without friction, drop
a large dependency, and be legible in one file.

Rejected because the architecture document names LangGraph, and a submission
that quietly substitutes its own runtime invites the question of whether the
author can use the ecosystem tools they specified. The friction above is a
real cost, but it is a cost of the tool, not of the decision, and it is
bounded to one file.
