# ADR-0001 — Distilled classifier with an LLM tail

**Status:** Accepted · Stage is out of scope for this package

## Context

~5,000 complaints a week need a category, sentiment, vulnerability and
detriment assessment, with evidence spans and a confidence score. The output
feeds the trend numbers, so it must be stable enough that week-on-week
comparison measures customer behaviour rather than classifier drift.

## Decision

An encoder classifier (distilled from LLM-labelled data) handles the bulk. The
low-confidence tail — near a decision boundary, or high novelty — goes to an
LLM.

## Consequences

Cheaper and faster per record, and materially easier to validate: a fixed
encoder has a versionable weight file, a reproducible confusion matrix, and a
calibration curve. A model validator can be given all three. It is also
deterministic, which matters because the classifier output is what the trend
series is built on.

The LLM keeps the thing encoders are worst at: novel phrasing and genuinely
ambiguous cases. Those are a small share of volume and a large share of the
cases where a wrong answer is expensive.

The cost is two components to maintain, two failure modes, and a routing
threshold that itself needs monitoring. Distillation also needs periodic
refresh as language and products change.

## Alternatives rejected

**LLM-only.** Simplest to build. Rejected: cost at 250k records a year,
latency, non-determinism between model versions (which corrupts trend
comparability), and a validation story that amounts to "we sampled some".

**Classical ML only.** Cheapest, most auditable. Rejected: fails on novel
complaint types, which is precisely the emerging-risk signal the product
exists to surface.
