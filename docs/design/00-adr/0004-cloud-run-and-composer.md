# ADR-0004 — Cloud Run and Composer, not GKE

**Status:** Accepted · Infrastructure is out of scope for this package

## Context

The workload is a weekly batch: enrich ~5,000 records, compute metrics, run one
bounded agent, render a report. Peak concurrency is low, and the whole run
takes minutes. Nothing is long-lived or stateful.

## Decision

Cloud Run for services and jobs, Composer (or Cloud Workflows) for the weekly
orchestration, Terraform for infrastructure, Artifact Registry for images,
GitHub Actions for CI.

## Consequences

Scale-to-zero between weekly runs, so cost tracks usage rather than capacity.
No cluster to patch, size or upgrade. The team maintaining this is a data
science function, not a platform team, and a Kubernetes cluster is a standing
operational commitment they would carry for a job that runs once a week.

Composer is chosen over Cloud Workflows where the DAG needs backfill and
retry semantics that are more than a state machine expresses comfortably;
Workflows is adequate if the pipeline stays this simple, and is cheaper.

## Alternatives rejected

**GKE.** Rejected: the constraint here is analytical quality, not compute
scale. A cluster would be sized for a peak that lasts minutes a week, and its
operational surface would exceed the pipeline's.

**Cloud Functions.** Rejected: the enrichment stage exceeds comfortable
timeout and memory limits, and the container story is worse than Cloud Run's
for a job that needs a pinned model runtime.
