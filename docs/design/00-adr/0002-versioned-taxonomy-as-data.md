# ADR-0002 — The taxonomy is versioned data, not code

**Status:** Accepted · Stage is out of scope for this package

## Context

The report's core value is comparability over time: "payments complaints rose
20% this week" is only meaningful if the category meant the same thing last
week. Category definitions do change — products launch, a broad category needs
splitting, a narrow one dies.

If the taxonomy lives in code, a redefinition silently rewrites history, and
nobody can tell a real movement from a definitional one.

## Decision

The taxonomy is held as versioned data: node definitions, inclusion and
exclusion criteria, exemplars, validity dates, and old→new mapping tables.
Never mutated in place. Every enriched record is stamped with the version used.

Structural changes mint a new version plus a mapping, allowing history to be
re-projected so trend series stay comparable. Re-projection produces a **new
run**, not an edit — otherwise a published report stops reconciling with the
store it cites.

Two routes to change, both human-gated:

| Route | Cadence | Change | Cost |
|---|---|---|---|
| Discovery over the residual pool | Weekly | Additive — new node | Cheap; history unaffected |
| Taxonomy health review | Periodic | Splits, merges, retirements | Breaks the series; needs re-projection |

## Consequences

Month-to-month comparability is guaranteed rather than hoped for, and any
historical report can be regenerated exactly.

Adding a category becomes a governed act with a lead time. That is the point —
but it is why **reporting** an emerging theme deliberately bypasses change
control. Reporting must be fast, because lead time is the entire value of
emerging-risk detection; adoption is structural and deliberately slow. A
candidate theme reaches the report as narrative with evidence, never as a row
in the trend table, because it has no comparable history.

## Alternatives rejected

**Fixed taxonomy.** Rejected: guarantees the emerging-risk requirement cannot
be met, since anything new has nowhere to go.

**Fully dynamic clustering, no fixed categories.** Rejected: clusters are not
stable across weeks without linking, and even with it the labels drift. Trend
comparison becomes impossible, which is most of the product.
