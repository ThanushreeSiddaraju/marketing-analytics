-- Paid + owned funnel from impression to paying customer, with step drop-off.
WITH paid_leads AS (
    SELECT * FROM fact_leads WHERE campaign_id IS NOT NULL
), stages AS (
    SELECT 1 AS step, 'Impressions' AS stage, SUM(impressions) AS volume FROM fact_ad_daily
    UNION ALL SELECT 2, 'Clicks',    SUM(clicks) FROM fact_ad_daily
    UNION ALL SELECT 3, 'Visits',    COUNT(*) FROM fact_sessions WHERE campaign_id IS NOT NULL
    UNION ALL SELECT 4, 'Leads',     COUNT(*) FROM paid_leads
    UNION ALL SELECT 5, 'MQLs',      COUNT(*) FROM paid_leads WHERE is_mql
    UNION ALL SELECT 6, 'SQLs',      COUNT(*) FROM paid_leads WHERE is_sql
    UNION ALL SELECT 7, 'Customers', COUNT(*) FROM paid_leads WHERE is_customer
)
SELECT
    step,
    stage,
    volume,
    ROUND(volume / FIRST_VALUE(volume) OVER (ORDER BY step), 6)        AS pct_of_top,
    ROUND(volume / LAG(volume) OVER (ORDER BY step), 4)                AS step_conversion,
    ROUND(1 - volume / LAG(volume) OVER (ORDER BY step), 4)            AS step_drop_off,
    LAG(volume) OVER (ORDER BY step) - volume                          AS lost
FROM stages
ORDER BY step;
