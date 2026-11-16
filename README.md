# Marketing Analytics

I wanted a project that looks at marketing the way a growth team actually does: which channels bring in paying customers, where people drop off between seeing an ad and paying, and where the budget should go next month.

There's no public dataset that covers ads, website visits, CRM stages and revenue for the same company, so I wrote a generator for one. It's a made-up B2B SaaS called Lumora with three plans ($49, $149 and $499 a month) and 19 campaigns across Google, Meta, LinkedIn, TikTok, email and affiliates for 2025. The channel numbers (CPMs, click rates, conversion rates, churn) are set to roughly what you'd see in the real world, and I put some messy data in on purpose so the cleaning step has something to do.

Everything else is DuckDB and SQL, with a bit of Python to run it.

## What I found

Over the year Lumora spent about $309k on ads, got 9,939 leads and 623 paying customers, and collected $522k. Ads paid back 1.14x within the first year and a paying customer from ads cost $762 on average.

| Channel | Spend | Customers | Cost per customer | Return in year 1 | LTV / CAC |
|---|---:|---:|---:|---:|---:|
| Email | $6.2k | 92 | $68 | 14.6x | 80.7 |
| Affiliate | $19.8k | 37 | $536 | 1.59x | 5.8 |
| Google Search | $101.4k | 162 | $626 | 1.32x | 4.9 |
| LinkedIn | $56.8k | 45 | $1,263 | 1.11x | 7.1 |
| Meta | $71.5k | 58 | $1,233 | 0.37x | 1.4 |
| Google Display | $32.8k | 8 | $4,100 | 0.20x | 0.3 |
| TikTok | $20.6k | 4 | $5,149 | 0.03x | 0.1 |

Display and TikTok together were 17% of the budget and brought in 12 customers out of 623. That's the easiest money to move.

LinkedIn looks bad if you only look at cost per customer, since it's twice what Google Search costs. But LinkedIn customers sign up for bigger plans and churn at about half the rate, so it ends up with the best lifetime value to cost ratio of any paid channel. I'd keep it.

Meta and Display mostly start journeys rather than finish them. With last-touch attribution Meta gets 5% of the revenue credit, but with first-touch it gets 14.5%. So if I were cutting Meta prospecting I'd do it slowly and keep an eye on Search and email volume.

Mobile clicks are cheap but convert at roughly half the rate of desktop. In North America and Europe, mobile traffic didn't pay for itself. The sign-up form on mobile is the first thing I'd look at.

Free-trial ads got about 20% more clicks than the average ad on the same channel and converted best once people landed. Ebook offers did worst.

For every channel, the step that loses the most people is between sales-qualified lead and customer. Only a quarter of SQLs buy, which is more of a sales and pricing question than a marketing one.

The cleaning step caught 403 duplicate ad rows, 15 negative spend values, 20 rows with more clicks than impressions, 2,618 channel names spelled differently (facebook, FB Ads, meta...), 1,277 visits with no device, and 30 duplicate leads from the CRM. It also flagged a day in August where Google Display billed spend but reported zero impressions. Details are in [output/00_data_quality.csv](output/00_data_quality.csv).

All of this is from the generated data (seed 42), so the numbers are only as real as my assumptions. The SQL doesn't care where the data comes from, though. Real exports from Google Ads, Meta, GA4 and a CRM mapped to the same columns would work the same way.

## How it's put together

Raw CSVs go into DuckDB, get cleaned in `sql/model/01_staging.sql`, and end up as a small star schema in `sql/model/02_marts.sql`:

- `fact_ad_daily`: spend, impressions and clicks by day, creative, device and region
- `fact_sessions`: one row per website visit
- `fact_leads`: one row per lead with MQL, SQL and won dates, plan and revenue so far
- `fact_orders`: monthly subscription invoices
- `fact_journeys`: every visit a lead made before converting, used for attribution
- `dim_date`, `dim_channel`, `dim_campaign`, `dim_creative`

The questions are answered in `sql/analysis/`:

| Query | What it answers |
|---|---|
| 01_channel_performance | Spend, CTR, CPC, cost per lead, CAC and ROAS by channel |
| 02_campaign_performance | The same by campaign, ranked |
| 03_marketing_funnel | Impressions to customers, with drop-off at each step |
| 04_funnel_by_channel | Where each channel's leads fall out of the sales pipeline |
| 05_monthly_trends | Spend, leads, new customers and revenue by month |
| 06_segment_performance | Device and region |
| 07_ltv_cac | Churn, lifetime value, LTV/CAC and payback period |
| 08_attribution_rules | First touch, last touch, linear and 40/20/40 |
| 09_creative_performance | Which offers, tones and formats get clicks |
| 10_kpi_summary | Headline numbers |

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python src/make_sample_data.py
python src/run_analysis.py
python -m pytest -q tests
```

Results go to `output/`, one CSV per query plus an Excel file with everything in it. The tests check things like the funnel never getting bigger, spend totals matching, and attribution credit adding up to one per lead.

## What's next

I'm adding a modelling layer next: data-driven attribution (Markov chains and Shapley values), a lead scoring model, and a marketing mix model to see where extra spend stops paying off. After that I'll build a small team of LLM agents that check the data, answer questions in SQL and write up the findings, with a reviewer that re-runs every number before it's published. The end goal is a dashboard site for all of it. My notes on the plan and on getting real data are in [docs/](docs/).
