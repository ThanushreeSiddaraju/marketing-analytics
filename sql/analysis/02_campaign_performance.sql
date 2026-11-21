-- Every campaign's funnel, cost and return, ranked by ROAS.
WITH ads AS (
    SELECT campaign_id, SUM(impressions) AS impressions, SUM(clicks) AS clicks, SUM(spend) AS spend
    FROM fact_ad_daily GROUP BY campaign_id
), visits AS (
    SELECT campaign_id, COUNT(*) AS visits FROM fact_sessions WHERE campaign_id IS NOT NULL GROUP BY campaign_id
), crm AS (
    SELECT campaign_id, COUNT(*) AS leads, COUNT(*) FILTER (is_customer) AS customers, SUM(revenue) AS revenue
    FROM fact_leads WHERE campaign_id IS NOT NULL GROUP BY campaign_id
)
SELECT
    c.campaign_id,
    c.campaign_name,
    c.channel,
    c.objective,
    c.start_date,
    c.end_date,
    ROUND(a.spend, 2)                                   AS spend,
    a.impressions,
    a.clicks,
    v.visits,
    COALESCE(m.leads, 0)                                AS leads,
    COALESCE(m.customers, 0)                            AS customers,
    ROUND(COALESCE(m.revenue, 0), 2)                    AS revenue,
    ROUND(a.clicks / NULLIF(a.impressions, 0), 4)       AS ctr,
    ROUND(a.spend / NULLIF(a.clicks, 0), 2)             AS cpc,
    ROUND(m.leads / NULLIF(v.visits, 0), 4)             AS visit_to_lead,
    ROUND(a.spend / NULLIF(m.leads, 0), 2)              AS cost_per_lead,
    ROUND(a.spend / NULLIF(m.customers, 0), 2)          AS cac,
    ROUND(COALESCE(m.revenue, 0) / NULLIF(a.spend, 0), 2) AS roas,
    RANK() OVER (ORDER BY COALESCE(m.revenue, 0) / NULLIF(a.spend, 0) DESC) AS roas_rank
FROM dim_campaign c
LEFT JOIN ads a    USING (campaign_id)
LEFT JOIN visits v USING (campaign_id)
LEFT JOIN crm m    USING (campaign_id)
ORDER BY roas_rank, campaign_id;
