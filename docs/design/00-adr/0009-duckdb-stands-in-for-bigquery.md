# ADR-0009 — DuckDB stands in for BigQuery in this package

**Status:** Accepted · Applies to the demonstration only

## Context

The architecture specifies BigQuery as the complaint store and the vector
index. This package must run offline with no cloud account, so something has
to stand in for it. The choice determines how much of the real data layer a
reviewer can actually see.

## Decision

DuckDB over Parquet, behind the repository protocols in
`store/protocols.py`. `store/bigquery_store.py` is a documented stub carrying
the production SQL and raising `NotImplementedError` — visible, unexecuted.

SQL views use the names from architecture §7 (`v_weekly_category_counts`,
`v_sentiment_by_channel_week`, `v_candidate_themes`, …) so the code and the
design document reconcile. Vector search uses DuckDB's
`array_cosine_similarity` with metadata filters applied inside the query,
which is the same shape as BigQuery `VECTOR_SEARCH` with a pre-filter.

## Consequences

A reviewer reads real SQL against real columns, not pandas `groupby` calls
standing in for a warehouse. The queries transfer to BigQuery with small
edits.

**Known dialect deltas**, which a migration would have to address:

| Here | BigQuery |
|---|---|
| `array_cosine_similarity(a, b)` with explicit `ORDER BY … LIMIT` | `VECTOR_SEARCH(…, top_k => n)`, returns distance not similarity |
| `FLOAT[n]` fixed-size list | `ARRAY<FLOAT64>` |
| `ORDER BY ALL` | Not supported; columns listed explicitly |
| No partitioning | Partition by `week`, cluster by `category` |
| `STDDEV_SAMP` | Same, but `SAFE.` prefixes needed for divide-by-zero |

`ORDER BY ALL` is not cosmetic: without an explicit sort DuckDB returns
aggregates in hash order, which varies between runs and would make the derived
facts — and so the report — differ on identical input. Invariant 6 fails there
first, and a test pins it.

## Alternatives rejected

**In-memory Python over Pydantic objects.** Fewest dependencies. Rejected: it
would hide the metrics layer's actual shape, and "we would write SQL in
production" is a claim a reviewer cannot check.

**Real BigQuery.** Rejected: breaks the offline guarantee.

**SQLite.** Rejected: no array type, so vector search would move into Python
and stop resembling the production query.
