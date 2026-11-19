-- Kevin Hillstrom's email experiment (MineThatData, 2008).
-- 64,000 customers who bought in the last 12 months were randomly split three ways:
-- a men's merchandise email, a women's merchandise email, or no email.
-- Outcomes were tracked for the two weeks after the send.
-- {csv} is replaced with the path to the downloaded file.

CREATE OR REPLACE TABLE hillstrom AS
SELECT
    row_number() OVER () AS customer_id,
    CASE segment WHEN 'Mens E-Mail' THEN 'mens_email'
                 WHEN 'Womens E-Mail' THEN 'womens_email'
                 ELSE 'control' END              AS arm,
    recency                                     AS months_since_purchase,
    history                                     AS spend_last_year,
    history_segment,
    mens = 1                                    AS bought_mens,
    womens = 1                                  AS bought_womens,
    CASE WHEN mens = 1 AND womens = 1 THEN 'both'
         WHEN mens = 1 THEN 'mens only'
         ELSE 'womens only' END                 AS bought,
    lower(replace(zip_code, 'Surburban', 'Suburban')) AS area,
    newbie = 1                                  AS new_customer,
    lower(channel)                              AS purchase_channel,
    visit = 1                                   AS visited,
    conversion = 1                              AS converted,
    spend
FROM read_csv('{csv}', header = true, columns = {
    'recency': 'INTEGER', 'history_segment': 'VARCHAR', 'history': 'DOUBLE',
    'mens': 'INTEGER', 'womens': 'INTEGER', 'zip_code': 'VARCHAR', 'newbie': 'INTEGER',
    'channel': 'VARCHAR', 'segment': 'VARCHAR', 'visit': 'INTEGER', 'conversion': 'INTEGER',
    'spend': 'DOUBLE'});
