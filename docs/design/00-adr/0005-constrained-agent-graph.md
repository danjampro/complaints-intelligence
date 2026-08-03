# ADR-0005 — A constrained agent graph, not an autonomous ReAct agent

**Status:** Accepted

## Context

Part of this workload genuinely needs agency. Remediation is
retrieve → assess relevance → refine, and the number of iterations depends on
what comes back. Candidate adjudication branches on the evidence. Neither path
is enumerable in advance, so a fixed prompt chain would either over-fetch or
give up too early.

But this is a regulated reporting product. An agent that decides its own steps
is an agent whose behaviour differs week to week, which destroys
comparability, and whose cost is unbounded.

## Decision

A **bounded graph** with fixed nodes and one conditional edge:

```
plan → investigate → adjudicate → remediate → critic ⇄ revise → render
```

Agency is confined to *what to look at next* and *what the evidence means*.
Determinism governs *what the numbers are*, *which stages run*, and *when the
run stops*.

Concretely:

- Tools are parameterised and allowlisted. There is no free-form SQL — it is
  absent from the interface, not forbidden by instruction.
- Every stage has a budget. Exhaustion produces a partial report with a
  recorded reason, not a crash and not an unbounded retry.
- The revise loop is capped at two rounds.
- `render` is outside the graph entirely, so the stage that substitutes real
  figures into prose cannot be reached by a revision.

## Consequences

Runs are comparable between weeks, because the same stages run in the same
order over the same shape of input. Cost is bounded and predictable. The trace
is a fixed shape, which makes it queryable.

The agent cannot pursue a line of enquiry the graph does not have a node for.
If a finding would benefit from checking the change calendar, and no such tool
exists, it will not be checked. This is the intended trade: the extension path
is to add a tool to `investigate`, which is a reviewed change with a diff.

## Alternatives rejected

**Single-shot prompt.** Rejected: cannot express the retrieve-assess-refine
loop that remediation needs, so recommendations would rest on whatever the
first retrieval happened to return.

**Autonomous ReAct agent.** Free tool choice, self-directed termination.
Rejected on three counts: behaviour is not comparable week to week, which
breaks the trend product; cost is unbounded; and a model validator cannot
assess a system whose control flow is emergent. The flexibility buys nothing
here — the set of useful next actions is small and known.

## What would change our mind

If the number of distinct investigation shapes grew past what a fixed graph
can express — many tool types, deep conditional chains — the maintenance cost
of the graph would exceed the audit benefit. The likely answer even then is a
graph per report section, not free-form agency.
