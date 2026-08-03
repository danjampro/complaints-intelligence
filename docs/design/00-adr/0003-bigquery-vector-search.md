# ADR-0003 — BigQuery vector search, not a dedicated vector database

**Status:** Accepted

## Context

Two retrieval workloads: exemplar complaints for investigation, and resolution
notes for remediation. Corpus is ~250k complaints a year, growing linearly.
Both are batch, weekly, with no interactive latency requirement.

## Decision

`VECTOR_SEARCH` in BigQuery, against embeddings stored alongside the
complaints they belong to.

## Consequences

No new datastore, no separate sync, and — the main benefit — no possibility of
the index disagreeing with the system of record, because they are the same
table. Metadata filters and similarity ranking happen in one query, so a
retrieval scoped to a week and category cannot return anything outside it.

At this corpus size and a weekly cadence, a purpose-built ANN index would buy
latency nobody is asking for. Vertex AI Vector Search is the documented
scale-out path if interactive drill-down is ever added.

## Alternatives rejected

**Dedicated vector database** (Pinecone, Weaviate, pgvector). Rejected: adds a
service to run, a sync pipeline to keep correct, and a second place for the
data to be wrong — in exchange for latency the workload does not need. The
sync is the real objection: an index that silently lags the store produces
citations to complaints that have since been amended.
