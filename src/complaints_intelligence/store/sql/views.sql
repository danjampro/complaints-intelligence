-- Parameterised views over the complaint store.
--
-- Names match architecture section 7 so the code and the design document
-- reconcile. In production these are dbt models over BigQuery; here they are
-- DuckDB views over Parquet.
--
-- Dialect deltas against BigQuery:
--   * DuckDB `array_cosine_similarity` stands in for BigQuery `VECTOR_SEARCH`.
--     BigQuery returns distance and takes a top-k argument; DuckDB returns
--     similarity and needs an explicit ORDER BY / LIMIT.
--   * BigQuery restricts a vector search to a subset by searching a filtered
--     embedding table — `VECTOR_SEARCH(v_precedent_embeddings, ...)`. Here the
--     equivalent is joining the vector table to `v_precedent` inside the
--     query, so the restriction still applies before ranking rather than
--     after.
--   * BigQuery would partition these tables by `week` and cluster by
--     `category`. DuckDB has no equivalent and does not need one at this size.
--   * `LIST` / `STRUCT` here would be `ARRAY` / `STRUCT` in BigQuery.
--
-- These views are the agent's entire reachable surface. There is no view that
-- accepts arbitrary predicates, which is what makes `query_metrics` a bounded
-- tool rather than a SQL prompt.

-- Base tables, registered by DuckDBStore from Parquet.

-- Assigned complaints only: the attribution track, and the numbers behind
-- drivers and sentiment trends. Abstained records are deliberately excluded
-- from per-category trends but still count in totals (see v_health_indicators),
-- so hard cases are never dropped from the denominator.
CREATE OR REPLACE VIEW v_weekly_category_counts AS
SELECT
    week,
    category,
    taxonomy_version,
    COUNT(*) AS complaint_count
FROM complaints
WHERE routing = 'assign'
GROUP BY week, category, taxonomy_version;

-- Volumes broken down by channel, so a movement can be attributed to where it
-- actually surfaced rather than reported as a firm-wide total.
CREATE OR REPLACE VIEW v_weekly_category_channel_counts AS
SELECT
    week,
    category,
    channel,
    COUNT(*) AS complaint_count
FROM complaints
WHERE routing = 'assign'
GROUP BY week, category, channel;

-- Sentiment aggregated WITHIN channel. Never pooled across channels: a branch
-- note and a call transcript have systematically different registers, so a
-- pooled mean moves whenever the channel mix moves, which is not a change in
-- what customers feel.
-- `stddev_sentiment` is carried because the shift is tested, not merely
-- thresholded. A difference of means without a dispersion is not a comparison,
-- and small cells would otherwise dominate the signal list through sampling
-- noise alone.
CREATE OR REPLACE VIEW v_sentiment_by_channel_week AS
SELECT
    week,
    channel,
    category,
    COUNT(*)                        AS complaint_count,
    AVG(sentiment)                  AS mean_sentiment,
    COALESCE(STDDEV_SAMP(sentiment), 0.0) AS stddev_sentiment
FROM complaints
WHERE routing = 'assign'
GROUP BY week, channel, category;

-- Channel-normalised sentiment for a week: each channel's mean weighted by a
-- fixed reference mix, so the index does not drift with volume mix.
CREATE OR REPLACE VIEW v_sentiment_by_week AS
SELECT
    week,
    AVG(mean_sentiment) AS mean_sentiment,
    SUM(complaint_count) AS complaint_count
FROM (
    SELECT week, channel, AVG(sentiment) AS mean_sentiment, COUNT(*) AS complaint_count
    FROM complaints
    WHERE routing = 'assign'
    GROUP BY week, channel
)
GROUP BY week;

-- Pipeline health. Abstention rate is a monitored signal, not a failure, but a
-- sharp move in it changes how every other number should be read.
CREATE OR REPLACE VIEW v_health_indicators AS
SELECT
    week,
    COUNT(*)                                          AS total_complaints,
    COUNT(*) FILTER (WHERE routing = 'abstain')       AS abstained_count,
    COUNT(*) FILTER (WHERE routing = 'abstain')::DOUBLE
        / NULLIF(COUNT(*), 0)                         AS abstention_rate,
    COUNT(*) FILTER (WHERE candidate_theme_id IS NOT NULL)::DOUBLE
        / NULLIF(COUNT(*), 0)                         AS residual_share,
    COUNT(*) FILTER (WHERE status = 'closed')         AS closed_count
FROM complaints
GROUP BY week;

-- Candidate themes: persistent clusters in the residual pool.
--
-- `duplicate_ratio` is computed from the data rather than declared. A cluster
-- whose members are mostly the same text is an ingest artefact, not a theme,
-- and that has to be measured to be trusted.
CREATE OR REPLACE VIEW v_candidate_themes AS
SELECT
    week,
    candidate_theme_id                                     AS theme_id,
    COUNT(*)                                               AS member_count,
    COUNT(DISTINCT channel)                                AS channel_count,
    MAX(channel_share)                                     AS channel_concentration,
    1.0 - (COUNT(DISTINCT text)::DOUBLE / NULLIF(COUNT(*), 0)) AS duplicate_ratio,
    AVG(novelty)                                           AS mean_novelty,
    AVG(confidence)                                        AS mean_confidence,
    AVG(sentiment)                                         AS mean_sentiment
FROM (
    SELECT
        *,
        COUNT(*) OVER (PARTITION BY week, candidate_theme_id, channel)::DOUBLE
            / COUNT(*) OVER (PARTITION BY week, candidate_theme_id) AS channel_share
    FROM complaints
    WHERE candidate_theme_id IS NOT NULL
)
GROUP BY week, candidate_theme_id;

-- The precedent pool: closed complaints that carry a resolution note.
--
-- Precedent retrieval is complaint-to-complaint. The agent matches a finding
-- against the complaint text of closed cases and reaches the note by this
-- join, rather than searching the notes directly — a symmetric comparison
-- against text of the same kind, which is why one embedding space serves it.
--
-- The restriction lives in the view, applied before ranking, rather than as a
-- filter over search results. Filtering afterwards degrades recall silently
-- whenever the nearest complaints happen to be mostly open.
--
-- `c.*` keeps every complaint column under its own name so the row
-- reconstructs into a `ComplaintEnvelope` unchanged. `r.category` is dropped
-- because it duplicates `c.category`.
CREATE OR REPLACE VIEW v_precedent AS
SELECT
    c.*,
    r.outcome,
    r.redress_gbp,
    r.days_to_close,
    r.text AS resolution_text
FROM complaints c
JOIN resolutions r USING (complaint_id)
WHERE c.status = 'closed';
