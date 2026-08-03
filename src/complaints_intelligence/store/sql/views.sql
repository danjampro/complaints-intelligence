-- Parameterised views over the complaint store.
--
-- Names match architecture section 7 so the code and the design document
-- reconcile. In production these are dbt models over BigQuery; here they are
-- DuckDB views over Parquet.
--
-- Dialect deltas against BigQuery, recorded in ADR-0009:
--   * DuckDB `array_cosine_similarity` stands in for BigQuery `VECTOR_SEARCH`.
--     BigQuery returns distance and takes a top-k argument; DuckDB returns
--     similarity and needs an explicit ORDER BY / LIMIT.
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
    COUNT(*)                                   AS complaint_count,
    COUNT(*) FILTER (WHERE detriment_flag)     AS detriment_count,
    COUNT(*) FILTER (WHERE vulnerability_flag) AS vulnerability_count
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

-- Resolution notes joined to their complaint, for remediation retrieval.
CREATE OR REPLACE VIEW v_resolution_candidates AS
SELECT
    r.complaint_id,
    r.category,
    r.outcome,
    r.redress_gbp,
    r.days_to_close,
    r.text          AS resolution_text,
    c.channel,
    c.week,
    c.text          AS complaint_text
FROM resolutions r
JOIN complaints c USING (complaint_id);
