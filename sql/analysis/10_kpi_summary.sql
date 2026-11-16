-- One-row headline KPIs for the dashboard and README.
SELECT
    ROUND((SELECT SUM(spend) FROM fact_ad_daily), 2)                                    AS total_spend,
    (SELECT SUM(impressions) FROM fact_ad_daily)                                        AS impressions,
    (SELECT SUM(clicks) FROM fact_ad_daily)                                             AS clicks,
    (SELECT COUNT(*) FROM fact_sessions)                                                AS visits,
    (SELECT COUNT(*) FROM fact_leads)                                                   AS leads,
    (SELECT COUNT(*) FROM fact_leads WHERE is_customer)                                 AS customers,
    ROUND((SELECT SUM(revenue) FROM fact_orders), 2)                                    AS revenue,
    ROUND((SELECT SUM(revenue) FROM fact_leads WHERE campaign_id IS NOT NULL), 2)       AS paid_revenue,
    ROUND((SELECT SUM(revenue) FROM fact_leads WHERE campaign_id IS NOT NULL)
          / (SELECT SUM(spend) FROM fact_ad_daily), 2)                                  AS paid_roas,
    ROUND((SELECT SUM(spend) FROM fact_ad_daily)
          / (SELECT COUNT(*) FROM fact_leads WHERE is_customer AND campaign_id IS NOT NULL), 2) AS paid_cac,
    ROUND((SELECT SUM(spend) FROM fact_ad_daily)
          / (SELECT COUNT(*) FROM fact_leads WHERE is_customer), 2)                     AS blended_cac,
    ROUND((SELECT SUM(clicks) FROM fact_ad_daily) * 1.0
          / (SELECT SUM(impressions) FROM fact_ad_daily), 4)                            AS ctr,
    ROUND((SELECT COUNT(*) FROM fact_leads) * 1.0 / (SELECT COUNT(*) FROM fact_sessions), 4) AS visit_to_lead,
    ROUND((SELECT AVG(is_customer::INT) FROM fact_leads), 4)                            AS lead_to_customer,
    ROUND((SELECT AVG(mrr) FROM fact_leads WHERE is_customer), 2)                       AS avg_mrr,
    (SELECT SUM(mrr) FROM fact_leads l WHERE is_customer AND EXISTS (
        SELECT 1 FROM fact_orders o WHERE o.user_id = l.user_id AND o.order_date >= DATE '2025-12-01')) AS ending_mrr;
