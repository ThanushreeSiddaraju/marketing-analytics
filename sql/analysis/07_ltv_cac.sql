-- Are customers from each channel worth what they cost?
-- Monthly churn = churned customers / customer-months observed.
-- A customer has churned if their last invoice is before the final month of data.
WITH last_month AS (
    SELECT MAX(DATE_TRUNC('month', order_date)) AS m FROM fact_orders
), cust AS (
    SELECT l.channel, l.user_id, l.mrr,
           MAX(o.order_date) AS last_order,
           COUNT(o.order_id) AS months_paid
    FROM fact_leads l JOIN fact_orders o USING (user_id)
    WHERE l.is_customer
    GROUP BY ALL
), by_channel AS (
    SELECT channel,
           COUNT(*)                                                     AS customers,
           AVG(mrr)                                                     AS avg_mrr,
           SUM(months_paid)                                             AS customer_months,
           COUNT(*) FILTER (DATE_TRUNC('month', last_order) < (SELECT m FROM last_month)) AS churned
    FROM cust GROUP BY channel
), spend AS (
    SELECT channel, SUM(spend) AS spend FROM fact_ad_daily GROUP BY channel
)
SELECT
    b.channel,
    d.channel_type,
    b.customers,
    ROUND(b.avg_mrr, 2)                                         AS avg_mrr,
    b.customer_months,
    b.churned,
    ROUND(b.churned / b.customer_months, 4)                     AS monthly_churn,
    -- lifetime value = average MRR / monthly churn, capped at 36 months of revenue
    ROUND(b.avg_mrr * LEAST(b.customer_months / NULLIF(b.churned, 0), 36), 2) AS projected_ltv,
    ROUND(s.spend / b.customers, 2)                             AS cac,
    ROUND(b.avg_mrr * LEAST(b.customer_months / NULLIF(b.churned, 0), 36)
          / NULLIF(s.spend / b.customers, 0), 2)                AS ltv_to_cac,
    ROUND((s.spend / b.customers) / b.avg_mrr, 1)               AS payback_months
FROM by_channel b
JOIN dim_channel d USING (channel)
LEFT JOIN spend s USING (channel)
ORDER BY ltv_to_cac DESC NULLS LAST;
