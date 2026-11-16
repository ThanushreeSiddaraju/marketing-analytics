-- Device x region performance for paid traffic (spend from the ad platforms,
-- conversions from the landing session of each lead).
WITH ads AS (
    SELECT device, region, SUM(impressions) AS impressions, SUM(clicks) AS clicks, SUM(spend) AS spend
    FROM fact_ad_daily GROUP BY ALL
), v AS (
    SELECT device, region, COUNT(*) AS visits, AVG(bounced::INT) AS bounce_rate
    FROM fact_sessions WHERE campaign_id IS NOT NULL GROUP BY ALL
), l AS (
    SELECT device, region, COUNT(*) AS leads, COUNT(*) FILTER (is_customer) AS customers, SUM(revenue) AS revenue
    FROM fact_leads WHERE campaign_id IS NOT NULL GROUP BY ALL
)
SELECT
    device,
    region,
    ROUND(a.spend, 2)                              AS spend,
    a.clicks,
    v.visits,
    ROUND(v.bounce_rate, 4)                        AS bounce_rate,
    COALESCE(l.leads, 0)                           AS leads,
    COALESCE(l.customers, 0)                       AS customers,
    ROUND(COALESCE(l.revenue, 0), 2)               AS revenue,
    ROUND(a.clicks / NULLIF(a.impressions, 0), 4)  AS ctr,
    ROUND(l.leads / NULLIF(v.visits, 0), 4)        AS visit_to_lead,
    ROUND(a.spend / NULLIF(l.leads, 0), 2)         AS cost_per_lead,
    ROUND(a.spend / NULLIF(l.customers, 0), 2)     AS cac,
    ROUND(l.revenue / NULLIF(a.spend, 0), 2)       AS roas
FROM ads a
JOIN v USING (device, region)
LEFT JOIN l USING (device, region)
ORDER BY roas DESC NULLS LAST;
