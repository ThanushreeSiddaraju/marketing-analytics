-- Which ad creatives (offer, tone, format) earn clicks and leads?
WITH ads AS (
    SELECT creative_id, SUM(impressions) AS impressions, SUM(clicks) AS clicks, SUM(spend) AS spend
    FROM fact_ad_daily GROUP BY creative_id
), v AS (
    SELECT creative_id, COUNT(*) AS visits FROM fact_sessions WHERE creative_id IS NOT NULL GROUP BY creative_id
), l AS (
    SELECT creative_id, COUNT(*) AS leads, COUNT(*) FILTER (is_customer) AS customers, SUM(revenue) AS revenue
    FROM fact_leads WHERE creative_id IS NOT NULL GROUP BY creative_id
)
SELECT
    c.creative_id,
    c.channel,
    c.campaign_id,
    c.offer_type,
    c.tone,
    c.format,
    c.headline,
    c.cta,
    ROUND(a.spend, 2)                              AS spend,
    a.impressions,
    a.clicks,
    v.visits,
    COALESCE(l.leads, 0)                           AS leads,
    COALESCE(l.customers, 0)                       AS customers,
    ROUND(a.clicks / NULLIF(a.impressions, 0), 4)  AS ctr,
    ROUND(l.leads / NULLIF(v.visits, 0), 4)        AS visit_to_lead,
    ROUND(a.spend / NULLIF(l.leads, 0), 2)         AS cost_per_lead,
    -- CTR relative to the channel average, so creatives on different channels compare fairly
    ROUND((a.clicks / NULLIF(a.impressions, 0))
          / (SUM(a.clicks) OVER w / SUM(a.impressions) OVER w), 3) AS ctr_index_vs_channel
FROM dim_creative c
JOIN ads a USING (creative_id)
LEFT JOIN v USING (creative_id)
LEFT JOIN l USING (creative_id)
WINDOW w AS (PARTITION BY c.channel)
ORDER BY ctr_index_vs_channel DESC, creative_id;
