# Data dictionary

What's in each table of the star schema built by `sql/model/02_marts.sql`. Row counts are for the default sample (seed 42). The `raw_*` and `stg_*` tables are the same data before and during cleaning; everything downstream reads the tables below.

## Facts

### fact_ad_daily (134,448 rows)

One row per day, creative, device and region, from the ad platforms.

| Column | Type | Meaning |
|---|---|---|
| date | DATE | Day the ads ran |
| campaign_id | VARCHAR | Campaign, joins to dim_campaign |
| creative_id | VARCHAR | Ad creative, joins to dim_creative |
| device | VARCHAR | desktop, mobile or tablet |
| region | VARCHAR | North America, Europe, APAC or LATAM |
| impressions | BIGINT | Times the ad was shown (sends, for email) |
| clicks | BIGINT | Clicks; the few raw rows with more clicks than impressions are re-estimated from that creative's usual click rate |
| spend | DECIMAL(14,2) | Cost in USD, stored as an exact decimal so totals don't drift |
| channel | VARCHAR | Channel, joins to dim_channel |

### fact_sessions (259,738 rows)

One row per website visit, paid and unpaid.

| Column | Type | Meaning |
|---|---|---|
| session_id | VARCHAR | Visit id |
| user_id | VARCHAR | Visitor id, the same person across visits |
| ts | TIMESTAMP | When the visit started |
| date | DATE | Day of the visit |
| channel | VARCHAR | Where the visit came from, after mapping messy names (facebook, FB Ads...) to one label |
| campaign_id | VARCHAR | Campaign, empty for organic, direct and referral visits |
| creative_id | VARCHAR | Ad clicked, if any |
| device | VARCHAR | desktop, mobile, tablet, or unknown when the tracker didn't record it |
| region | VARCHAR | Visitor region |
| pageviews | INTEGER | Pages viewed in the visit |
| duration_sec | INTEGER | Visit length in seconds |
| bounced | BOOLEAN | Left after one page |

### fact_leads (9,939 rows)

One row per lead, from the CRM, with the visit that produced it and everything that happened after.

| Column | Type | Meaning |
|---|---|---|
| lead_id | VARCHAR | Lead id, unique after removing CRM duplicates |
| user_id | VARCHAR | The visitor who became the lead |
| session_id | VARCHAR | The visit where they filled in the form |
| created_at | TIMESTAMP | When the lead was created |
| channel | VARCHAR | Channel of that visit, so this is last-touch attribution |
| campaign_id | VARCHAR | Campaign of that visit, if paid |
| company_size | VARCHAR | 1-10, 11-50, 51-200, 201-1000 or 1000+ |
| industry | VARCHAR | Industry from the form |
| mql_at, sql_at, won_at | TIMESTAMP | When the lead became marketing-qualified, sales-qualified, and a paying customer |
| plan | VARCHAR | Starter, Pro or Business, for customers |
| mrr | DOUBLE | Monthly recurring revenue at signup ($49, $149 or $499) |
| device, region, creative_id | VARCHAR | Taken from the landing visit |
| landing_pageviews | INTEGER | Pages viewed in the landing visit |
| is_mql, is_sql, is_customer | BOOLEAN | Funnel stage flags |
| won_date | DATE | Day they became a customer |
| days_to_win | BIGINT | Days from lead to customer |
| revenue | DOUBLE | Revenue collected from this customer in 2025 |
| paid_months | BIGINT | Monthly invoices paid in 2025 |

### fact_orders (3,136 rows)

One row per monthly subscription invoice.

| Column | Type | Meaning |
|---|---|---|
| order_id | VARCHAR | Invoice id |
| user_id | VARCHAR | Customer, joins to fact_leads.user_id |
| order_date | DATE | Invoice date |
| revenue | DOUBLE | Amount billed |
| plan | VARCHAR | Plan on the invoice |
| is_first_order | BOOLEAN | The customer's first invoice |

### fact_journeys (19,471 rows)

Every visit a lead made up to and including the one where they converted. This is what the attribution models read.

| Column | Type | Meaning |
|---|---|---|
| lead_id | VARCHAR | The lead |
| is_customer | BOOLEAN | Whether that lead went on to pay |
| revenue | DOUBLE | That lead's 2025 revenue |
| session_id | VARCHAR | The visit |
| ts | TIMESTAMP | When the visit happened |
| channel | VARCHAR | Channel of the visit |
| campaign_id | VARCHAR | Campaign of the visit, if paid |
| touch_number | BIGINT | 1 for the first visit, up to `touches` |
| touches | BIGINT | Total visits in this lead's journey |

## Dimensions

### dim_date (365 rows)

| Column | Type | Meaning |
|---|---|---|
| date | DATE | Every day of 2025 |
| year, month | BIGINT | Calendar parts |
| year_month | VARCHAR | e.g. 2025-03, used for monthly rollups |
| week_start | DATE | Monday of that week |
| weekday | VARCHAR | Day name |
| is_weekend | BOOLEAN | Saturday or Sunday |

### dim_channel (10 rows)

| Column | Type | Meaning |
|---|---|---|
| channel | VARCHAR | Google Search, Google Display, Meta Ads, LinkedIn Ads, TikTok Ads, Email, Affiliate, Organic Search, Direct, Referral |
| channel_type | VARCHAR | Paid, Owned (email) or Organic |

### dim_campaign (19 rows)

| Column | Type | Meaning |
|---|---|---|
| campaign_id | VARCHAR | C001 to C019 |
| campaign_name | VARCHAR | Channel and campaign, e.g. "Google Search \| Brand Keywords" |
| channel | VARCHAR | Channel the campaign runs on |
| objective | VARCHAR | Awareness, Conversion, Lead Gen or Retention |
| start_date, end_date | DATE | When it ran |
| daily_budget | DOUBLE | Average planned daily budget in USD |

### dim_creative (38 rows)

Two creatives per campaign.

| Column | Type | Meaning |
|---|---|---|
| creative_id | VARCHAR | e.g. C001-1 |
| campaign_id | VARCHAR | Parent campaign |
| offer_type | VARCHAR | Free trial, Demo booking, Discount, Webinar or Ebook |
| tone | VARCHAR | Data-driven, Urgent, Friendly or Bold |
| format | VARCHAR | Video, Carousel, Image or Text |
| headline, cta | VARCHAR | Ad text and call to action |
| channel | VARCHAR | Channel the creative runs on |

## Real data: hillstrom

Built by `sql/real/01_hillstrom.sql` in its own in-memory database, one row per customer (64,000).

| Column | Type | Meaning |
|---|---|---|
| customer_id | BIGINT | Row number |
| arm | VARCHAR | mens_email, womens_email or control |
| months_since_purchase | INTEGER | Months since last purchase, before the test |
| spend_last_year | DOUBLE | Spend in the year before the test (the CUPED covariate) |
| history_segment | VARCHAR | Last year's spend in bands |
| bought_mens, bought_womens | BOOLEAN | Had bought men's or women's merchandise before |
| bought | VARCHAR | mens only, womens only or both |
| area | VARCHAR | urban, suburban or rural |
| new_customer | BOOLEAN | First purchase was in the last 12 months |
| purchase_channel | VARCHAR | phone, web or multichannel |
| visited, converted | BOOLEAN | Visited the site / bought something in the two weeks after the email |
| spend | DOUBLE | Spend in those two weeks |
