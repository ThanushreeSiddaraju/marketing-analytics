-- Where each channel's visitors drop out (visit -> lead -> MQL -> SQL -> customer).
WITH v AS (SELECT channel, COUNT(*) AS visits FROM fact_sessions GROUP BY channel),
l AS (
    SELECT channel, COUNT(*) AS leads, COUNT(*) FILTER (is_mql) AS mqls,
           COUNT(*) FILTER (is_sql) AS sqls, COUNT(*) FILTER (is_customer) AS customers,
           ROUND(MEDIAN(days_to_win), 1) AS median_days_to_win
    FROM fact_leads GROUP BY channel
)
SELECT
    channel,
    d.channel_type,
    visits, leads, mqls, sqls, customers,
    ROUND(leads / visits, 4)                 AS visit_to_lead,
    ROUND(mqls / NULLIF(leads, 0), 4)        AS lead_to_mql,
    ROUND(sqls / NULLIF(mqls, 0), 4)         AS mql_to_sql,
    ROUND(customers / NULLIF(sqls, 0), 4)    AS sql_to_customer,
    ROUND(customers / visits, 5)             AS visit_to_customer,
    median_days_to_win,
    -- the sales-pipeline step that loses the biggest share of leads for this channel
    CASE GREATEST(1 - mqls / NULLIF(leads, 0), 1 - sqls / NULLIF(mqls, 0), 1 - customers / NULLIF(sqls, 0))
        WHEN 1 - mqls / NULLIF(leads, 0) THEN 'Lead -> MQL'
        WHEN 1 - sqls / NULLIF(mqls, 0) THEN 'MQL -> SQL'
        ELSE 'SQL -> Customer'
    END AS biggest_leak_after_lead
FROM v JOIN l USING (channel) JOIN dim_channel d USING (channel)
ORDER BY visit_to_customer DESC;
