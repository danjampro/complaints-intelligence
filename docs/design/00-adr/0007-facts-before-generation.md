# ADR-0007 — Facts are computed before generation

**Status:** Accepted

## Context

The report contains figures that must be correct, identical on every re-run,
and defensible to a regulator eighteen months later. It also contains prose
that a language model writes. The question is how the two meet.

The obvious arrangement is to give the model the data and ask it to write the
report, then check the numbers afterwards. This is what most systems do.

## Decision

Every figure is computed by ordinary code before any model is invoked and
stored as a **fact** with provenance. The model never writes a number. It
writes a **fact ID** in a placeholder, and the value is substituted at render
time from the fact store.

The same applies to quotations. A citation is a complaint ID plus character
offsets; the quoted text is sliced out of the store at render time. The model
never handles the words it quotes.

## Consequences

Numeric hallucination and misquotation become **structurally impossible**
rather than detected after the fact. The failure mode changes shape: instead
of a plausible wrong number reaching a reader, an invalid reference fails to
resolve and the run stops.

This is a stronger guarantee than post-hoc checking, and cheaper. Post-hoc
numeric verification requires parsing figures out of prose, matching them to
intended sources, and deciding whether a discrepancy is a rounding difference
or a fabrication. None of that is necessary if the model cannot type a digit.

The cost is that the metrics layer must precompute every figure the report
might want. A figure nobody anticipated cannot be cited. In practice this is
a feature: it forces the set of reportable measures to be an explicit,
reviewable list rather than whatever the model chose to calculate.

## Alternatives rejected

**Post-hoc numeric verification.** Let the model write numbers, then check
them. Rejected: it verifies a claim against a source the model chose, which
does not catch a number that is internally consistent and wrong. It also
cannot distinguish "142 complaints" that is right from one that is right by
coincidence.

**Tool-calling arithmetic.** Give the model a calculator. Rejected: it moves
the problem rather than solving it — the model still decides which numbers to
put in, and the audit trail becomes a sequence of tool calls rather than a
stored, re-derivable fact.

## What would change our mind

If the report needed genuinely ad-hoc analysis — a figure whose shape is not
known until the evidence is read — the precomputed set would become a
straitjacket. The answer then would be a parameterised analysis tool with its
own provenance record, not a model doing arithmetic.
