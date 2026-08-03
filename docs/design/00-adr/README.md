# Architecture Decision Records

Each record states the decision, the alternatives rejected, and what would
change our mind. Records are immutable once accepted; a reversal is a new
record that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-distilled-classifier-plus-llm-tail.md) | Distilled classifier with an LLM tail | Accepted |
| [0002](0002-versioned-taxonomy-as-data.md) | Taxonomy held as versioned data | Accepted |
| [0003](0003-bigquery-vector-search.md) | BigQuery vector search over a dedicated vector database | Accepted |
| [0004](0004-cloud-run-and-composer.md) | Cloud Run and Composer over GKE | Accepted |
| [0005](0005-constrained-agent-graph.md) | A constrained agent graph, not a ReAct agent | Accepted |
| [0006](0006-remediation-by-precedent.md) | Remediation by resolution-note retrieval | Accepted |
| [0007](0007-facts-before-generation.md) | Facts computed before generation | Accepted |
| [0008](0008-langgraph.md) | LangGraph as the graph runtime | Accepted |
| [0009](0009-duckdb-stands-in-for-bigquery.md) | DuckDB stands in for BigQuery in this package | Accepted |
| [0010](0010-tfidf-svd-embeddings.md) | TF-IDF + SVD stands in for a hosted embedding model | Accepted |
| [0011](0011-cassette-replay.md) | Cassette replay as the default LLM mode | Accepted |

Records 0001–0007 correspond to the Key decisions table in
[`../02-architecture.md`](../02-architecture.md). Records 0008–0011 cover
choices specific to this implementation.
