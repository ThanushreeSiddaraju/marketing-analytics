-- Month x channel spend, leads, new customers, new MRR and revenue collected.
WITH months AS (
    SELECT DISTINCT year_month FROM dim_date
), grid AS (
    SELECT m.year_month, c.channel FROM months m CROSS JOIN dim_channel c
), spend AS (
    SELECT STRFTIME(date, '%Y-%m') AS year_month, channel, SUM(spend) AS spend, SUM(clicks) AS clicks
    FROM fact_ad_daily GROUP BY ALL
), leads AS (
    SELECT STRFTIME(created_at, '%Y-%m') AS year_month, channel, COUNT(*) AS leads
    FROM fact_leads GROUP BY ALL
), wins AS (
    SELECT STRFTIME(won_at, '%Y-%m') AS year_month, channel, COUNT(*) AS new_customers, SUM(mrr) AS new_mrr
    FROM fact_leads WHERE is_customer GROUP BY ALL
), rev AS (
    SELECT STRFTIME(o.order_date, '%Y-%m') AS year_month, l.channel, SUM(o.revenue) AS revenue
    FROM fact_orders o JOIN fact_leads l USING (user_id) GROUP BY ALL
)
SELECT
    g.year_month,
    g.channel,
    ROUND(COALESCE(s.spend, 0), 2)                     AS spend,
    COALESCE(s.clicks, 0)                              AS clicks,
    COALESCE(l.leads, 0)                               AS leads,
    COALESCE(w.new_customers, 0)                       AS new_customers,
    COALESCE(w.new_mrr, 0)                             AS new_mrr,
    ROUND(COALESCE(r.revenue, 0), 2)                   AS revenue,
    ROUND(s.spend / NULLIF(l.leads, 0), 2)             AS cost_per_lead,
    ROUND(w.new_mrr * 12 / NULLIF(s.spend, 0), 2)      AS new_arr_per_dollar
FROM grid g
LEFT JOIN spend s USING (year_month, channel)
LEFT JOIN leads l USING (year_month, channel)
LEFT JOIN wins  w USING (year_month, channel)
LEFT JOIN rev   r USING (year_month, channel)
ORDER BY g.year_month, spend DESC;
