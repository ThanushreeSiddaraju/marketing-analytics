-- Spend efficiency and revenue by channel (last-touch attribution).
WITH ads AS (
    SELECT channel, SUM(impressions) AS impressions, SUM(clicks) AS clicks, SUM(spend) AS spend
    FROM fact_ad_daily GROUP BY channel
), visits AS (
    SELECT channel, COUNT(*) AS visits FROM fact_sessions GROUP BY channel
), crm AS (
    SELECT channel, COUNT(*) AS leads, COUNT(*) FILTER (is_mql) AS mqls, COUNT(*) FILTER (is_sql) AS sqls,
           COUNT(*) FILTER (is_customer) AS customers, SUM(revenue) AS revenue
    FROM fact_leads GROUP BY channel
)
SELECT
    d.channel,
    d.channel_type,
    ROUND(COALESCE(a.spend, 0), 2)                         AS spend,
    COALESCE(a.impressions, 0)                             AS impressions,
    COALESCE(a.clicks, 0)                                  AS clicks,
    v.visits,
    c.leads,
    c.mqls,
    c.sqls,
    c.customers,
    ROUND(c.revenue, 2)                                    AS revenue,
    ROUND(a.clicks / NULLIF(a.impressions, 0), 4)          AS ctr,
    ROUND(a.spend / NULLIF(a.clicks, 0), 2)                AS cpc,
    ROUND(a.spend * 1000 / NULLIF(a.impressions, 0), 2)    AS cpm,
    ROUND(c.leads / NULLIF(v.visits, 0), 4)                AS visit_to_lead,
    ROUND(c.customers / NULLIF(c.leads, 0), 4)             AS lead_to_customer,
    ROUND(a.spend / NULLIF(c.leads, 0), 2)                 AS cost_per_lead,
    ROUND(a.spend / NULLIF(c.customers, 0), 2)             AS cac,
    ROUND(c.revenue / NULLIF(a.spend, 0), 2)               AS roas,
    ROUND(c.revenue / SUM(c.revenue) OVER (), 4)           AS revenue_share
FROM dim_channel d
LEFT JOIN ads a    USING (channel)
LEFT JOIN visits v USING (channel)
LEFT JOIN crm c    USING (channel)
ORDER BY spend DESC, revenue DESC;
