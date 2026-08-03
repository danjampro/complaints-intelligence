# ADR-0006 — Remediation grounded in resolution precedent

**Status:** Accepted

## Context

The report must offer "remediation recommendations in plain English". The
failure mode is obvious and severe: a language model asked what to do about
failed payments will produce fluent, generic, plausible advice — "review the
payment gateway, improve customer communications" — that is indistinguishable
from a consultancy template and grounded in nothing.

## Decision

Recommendations are derived **only** from resolution notes on closed
complaints: free text recording what was actually done. The `remediate` node
retrieves comparable closed cases, assesses whether each genuinely transfers,
and summarises the actions that worked.

Retrieval is bounded but adaptive: the first pass is scoped to the finding's
category; if too few precedents transfer, it widens beyond the category and
retries once. Precedents that do **not** transfer are retained with their
reason and printed in the report.

## Consequences

Every recommendation is traceable to cases where that action was taken and to
the outcome it produced. "This is what we did last time and it worked" is a
defensible thing to put in front of a committee; "consider reviewing your
processes" is not.

Reporting the ruled-out precedents matters more than it looks. A report that
shows only supporting evidence is advocacy. Showing what was considered and
rejected, with reasons, is what makes the recommendation auditable.

The limitation is real: the system can only recommend what the firm has
already done. A genuinely novel problem yields no transferable precedent, and
the honest output is to say so rather than invent something. That is the
designed behaviour — `remediate` emits no recommendation and records why.

This is also the step that most justifies an agent (ADR-0005): retrieve,
assess, refine, with the iteration count depending on what comes back.

## Alternatives rejected

**Causal root-cause inference.** Ask the model to reason about why complaints
arose and what would fix it. Rejected: unfalsifiable output, and it invites
exactly the causal overreach the critic exists to prevent.

**Change-calendar correlation.** Correlate complaint spikes with releases.
Rejected as a *primary* source — correlation with a release is evidence for a
hypothesis, not a remediation — but it is the obvious next tool to add to
`investigate`, emitted as a hypothesis requiring confirmation by a named owner.

**Generic remediation playbook.** A curated library keyed by category.
Rejected: it is a maintenance burden that goes stale silently, and it cannot
reflect what actually worked for this firm.
