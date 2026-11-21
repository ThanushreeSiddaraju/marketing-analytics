-- Staging: load raw CSVs, then clean them.
-- {raw} is replaced with the raw-data folder by src/build_model.py.

CREATE OR REPLACE TABLE raw_campaigns AS SELECT * FROM read_csv_auto('{raw}/campaigns.csv', header = true);
CREATE OR REPLACE TABLE raw_creatives AS SELECT * FROM read_csv_auto('{raw}/creatives.csv', header = true);
CREATE OR REPLACE TABLE raw_ad_daily  AS SELECT * FROM read_csv_auto('{raw}/ad_daily.csv',  header = true);
CREATE OR REPLACE TABLE raw_sessions  AS SELECT * FROM read_csv_auto('{raw}/sessions.csv',  header = true);
CREATE OR REPLACE TABLE raw_leads     AS SELECT * FROM read_csv_auto('{raw}/leads.csv',     header = true);
CREATE OR REPLACE TABLE raw_orders    AS SELECT * FROM read_csv_auto('{raw}/orders.csv',    header = true);

-- Channel names arrive in several spellings from different tools.
CREATE OR REPLACE TABLE channel_map AS
SELECT * FROM (VALUES
    ('facebook',         'Meta Ads'),
    ('FB Ads',           'Meta Ads'),
    ('meta',             'Meta Ads'),
    ('google_search',    'Google Search'),
    ('Google - Search',  'Google Search'),
    ('organic',          'Organic Search'),
    ('google / organic', 'Organic Search'),
    ('linkedin',         'LinkedIn Ads')
) AS t(raw_name, channel);

CREATE OR REPLACE TABLE stg_campaigns AS
SELECT campaign_id, campaign_name, channel, objective,
       CAST(start_date AS DATE) AS start_date, CAST(end_date AS DATE) AS end_date,
       CAST(daily_budget AS DOUBLE) AS daily_budget
FROM raw_campaigns;

CREATE OR REPLACE TABLE stg_creatives AS
SELECT * FROM raw_creatives;

-- Ad platform rows: drop exact duplicates, fix sign-flipped spend,
-- cap clicks at impressions (a click needs an impression).
CREATE OR REPLACE TABLE stg_ad_daily AS
SELECT DISTINCT
    CAST(date AS DATE)                    AS date,
    campaign_id,
    creative_id,
    device,
    region,
    CAST(impressions AS BIGINT)           AS impressions,
    CAST(LEAST(clicks, impressions) AS BIGINT) AS clicks,
    -- stored as an exact decimal so totals don't depend on the order rows are added up
    CAST(ROUND(ABS(CAST(spend AS DOUBLE)), 2) AS DECIMAL(14, 2)) AS spend
FROM raw_ad_daily;

CREATE OR REPLACE TABLE stg_sessions AS
SELECT
    s.session_id,
    s.user_id,
    CAST(s.ts AS TIMESTAMP)               AS ts,
    CAST(s.ts AS DATE)                    AS date,
    COALESCE(m.channel, s.channel)        AS channel,
    s.campaign_id,
    s.creative_id,
    COALESCE(s.device, 'unknown')         AS device,
    s.region,
    CAST(s.pageviews AS INTEGER)          AS pageviews,
    CAST(s.duration_sec AS INTEGER)       AS duration_sec,
    CAST(s.bounced AS BOOLEAN)            AS bounced
FROM raw_sessions s
LEFT JOIN channel_map m ON s.channel = m.raw_name;

-- CRM export contains duplicated leads; keep one row per lead_id.
CREATE OR REPLACE TABLE stg_leads AS
SELECT
    l.lead_id,
    l.user_id,
    l.session_id,
    CAST(l.created_at AS TIMESTAMP)       AS created_at,
    COALESCE(m.channel, l.channel)        AS channel,
    l.campaign_id,
    l.company_size,
    l.industry,
    CAST(l.mql_at AS TIMESTAMP)           AS mql_at,
    CAST(l.sql_at AS TIMESTAMP)           AS sql_at,
    CAST(l.won_at AS TIMESTAMP)           AS won_at,
    l.plan,
    CAST(l.mrr AS DOUBLE)                 AS mrr
FROM raw_leads l
LEFT JOIN channel_map m ON l.channel = m.raw_name
QUALIFY ROW_NUMBER() OVER (PARTITION BY l.lead_id ORDER BY l.created_at) = 1;

CREATE OR REPLACE TABLE stg_orders AS
SELECT order_id, user_id, CAST(order_date AS DATE) AS order_date,
       CAST(revenue AS DOUBLE) AS revenue, plan, CAST(is_first_order AS BOOLEAN) AS is_first_order
FROM raw_orders;
