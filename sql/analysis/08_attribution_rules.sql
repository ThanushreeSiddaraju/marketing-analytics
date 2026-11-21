-- Who gets credit when a lead touched several channels?
-- Four rule-based models over the same journeys (visits up to the lead's conversion).
WITH weights AS (
    -- Exact decimals, so sums come out the same whatever order the rows are in.
    SELECT
        lead_id, channel, is_customer,
        CAST(revenue AS DECIMAL(14, 2))                                             AS revenue,
        CAST(CASE WHEN touch_number = 1 THEN 1 ELSE 0 END AS DECIMAL(18, 12))       AS first_touch,
        CAST(CASE WHEN touch_number = touches THEN 1 ELSE 0 END AS DECIMAL(18, 12)) AS last_touch,
        CAST(1.0 / touches AS DECIMAL(18, 12))                                      AS linear,
        CAST(CASE
            WHEN touches = 1 THEN 1.0
            WHEN touches = 2 THEN 0.5
            WHEN touch_number IN (1, touches) THEN 0.4
            ELSE 0.2 / (touches - 2)
        END AS DECIMAL(18, 12))                                                     AS position_based
    FROM fact_journeys
), long AS (
    UNPIVOT weights ON first_touch, last_touch, linear, position_based INTO NAME model VALUE credit
)
SELECT
    model,
    channel,
    ROUND(SUM(credit), 2)                                   AS leads,
    ROUND(SUM(credit * is_customer::INT), 2)                AS customers,
    ROUND(SUM(credit * revenue), 2)                         AS revenue,
    ROUND(SUM(credit * revenue) / SUM(SUM(credit * revenue)) OVER (PARTITION BY model), 4) AS revenue_share
FROM long
GROUP BY model, channel
ORDER BY model, revenue DESC, channel;
