-- Star schema: dimensions + facts used by every analysis query.

CREATE OR REPLACE TABLE dim_date AS
SELECT
    CAST(d AS DATE)                         AS date,
    EXTRACT(year FROM d)                    AS year,
    EXTRACT(month FROM d)                   AS month,
    STRFTIME(d, '%Y-%m')                    AS year_month,
    CAST(DATE_TRUNC('week', d) AS DATE)     AS week_start,
    DAYNAME(d)                              AS weekday,
    ISODOW(d) >= 6                          AS is_weekend
FROM RANGE(DATE '2025-01-01', DATE '2026-01-01', INTERVAL 1 DAY) AS t(d);

CREATE OR REPLACE TABLE dim_channel AS
SELECT
    channel,
    CASE
        WHEN channel = 'Email' THEN 'Owned'
        WHEN channel IN ('Organic Search', 'Direct', 'Referral') THEN 'Organic'
        ELSE 'Paid'
    END AS channel_type
FROM (SELECT DISTINCT channel FROM stg_sessions
      UNION SELECT DISTINCT channel FROM stg_campaigns);

CREATE OR REPLACE TABLE dim_campaign AS
SELECT * FROM stg_campaigns;

CREATE OR REPLACE TABLE dim_creative AS
SELECT cr.*, c.channel
FROM stg_creatives cr
JOIN stg_campaigns c USING (campaign_id);

CREATE OR REPLACE TABLE fact_ad_daily AS
SELECT a.*, c.channel
FROM stg_ad_daily a
JOIN stg_campaigns c USING (campaign_id);

CREATE OR REPLACE TABLE fact_sessions AS
SELECT * FROM stg_sessions;

CREATE OR REPLACE TABLE fact_orders AS
SELECT * FROM stg_orders;

-- One row per lead, with stage flags, the landing session's segment,
-- and revenue collected from that customer so far (last-touch attribution).
CREATE OR REPLACE TABLE fact_leads AS
WITH rev AS (
    SELECT user_id, SUM(revenue) AS revenue, COUNT(*) AS paid_months
    FROM fact_orders GROUP BY user_id
)
SELECT
    l.*,
    s.device,
    s.region,
    s.creative_id,
    s.pageviews                              AS landing_pageviews,
    l.mql_at IS NOT NULL                     AS is_mql,
    l.sql_at IS NOT NULL                     AS is_sql,
    l.won_at IS NOT NULL                     AS is_customer,
    CAST(l.won_at AS DATE)                   AS won_date,
    DATE_DIFF('day', l.created_at, l.won_at) AS days_to_win,
    COALESCE(r.revenue, 0)                   AS revenue,
    COALESCE(r.paid_months, 0)               AS paid_months
FROM stg_leads l
LEFT JOIN fact_sessions s ON s.session_id = l.session_id
LEFT JOIN rev r           ON r.user_id = l.user_id;

-- Every visit a lead made up to and including the visit where they converted.
-- This is the journey used by the attribution models.
CREATE OR REPLACE TABLE fact_journeys AS
SELECT
    l.lead_id,
    l.is_customer,
    l.revenue,
    s.session_id,
    s.ts,
    s.channel,
    s.campaign_id,
    ROW_NUMBER() OVER (PARTITION BY l.lead_id ORDER BY s.ts, s.session_id) AS touch_number,
    COUNT(*)     OVER (PARTITION BY l.lead_id)                             AS touches
FROM fact_leads l
JOIN fact_sessions s
  ON s.user_id = l.user_id
 AND s.ts <= l.created_at;
