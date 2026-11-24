# Marketing Analytics

The dashboard is at https://thanushreesiddaraju.github.io/marketing-analytics/

I wanted a project that looks at marketing the way a growth team actually does: which channels bring in paying customers, where people drop off between seeing an ad and paying, and where the budget should go next month.

There's no public dataset that covers ads, website visits, CRM stages and revenue for the same company, so I wrote a generator for one. It's a made-up B2B SaaS called Lumora with three plans ($49, $149 and $499 a month) and 19 campaigns across Google, Meta, LinkedIn, TikTok, email and affiliates for 2025. The channel numbers (CPMs, click rates, conversion rates, churn) are set to roughly what you'd see in the real world, and I put some messy data in on purpose so the cleaning step has something to do.

The data work is DuckDB and SQL, and the modelling, agents and site are in Python and plain JavaScript.

## What it covers

I built the whole thing myself, from the data to the page it's published on:

- SQL and data modelling: a DuckDB star schema with five fact tables and four dimensions, cleaning in staging SQL (`QUALIFY ROW_NUMBER()` dedupes, channel mapping, impossible values), and ten analysis queries using window functions, `UNPIVOT`, `FILTER` and `LAG`.
- Marketing analytics: CAC, ROAS, LTV to CAC, payback, churn, funnel conversion, creative and device performance, and first-touch, last-touch, linear and position-based attribution.
- Attribution modelling: Markov chain removal effects and exact Shapley values written from scratch, tested against hand-worked cases and against the SQL.
- Machine learning: lead scoring with XGBoost and logistic regression, no leakage, month-by-month validation, SHAP, calibration and lift.
- Mix modelling and optimisation: adstock and saturation curves with weak priors, bootstrap intervals, parameter recovery against known truth, and a constrained budget optimiser.
- Experiments and statistics: a real 64,000-customer randomised email test with sample ratio and balance checks, Welch intervals, Holm correction, CUPED, power analysis, segment effects and a held-out targeting check.
- LLM agents: four agents on the Anthropic SDK with tool use and structured outputs, two layers of SQL lockdown, every number re-checked in code, a reviewer agent and a 32-question eval.
- Engineering: a reproducible generator with planted data problems, 59 pytest tests, a ruff lint step, and GitHub Actions that rebuild the data, rerun every model and publish the site on every push.
- Data visualisation: hand-written SVG charts with no chart library, a colour-blind-checked palette, light and dark modes, tooltips and a table behind every chart.

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

Once someone becomes a lead, the step that loses the most people is between sales-qualified lead and customer, and that's true for every channel. Only a quarter of SQLs buy, which is more of a sales and pricing question than a marketing one.

The cleaning step caught 403 duplicate ad rows, 15 negative spend values, 20 rows with more clicks than impressions, 2,618 channel names spelled differently (facebook, FB Ads, meta...), 1,277 visits with no device, and 30 duplicate leads from the CRM. It also flagged a day in August where Google Display billed spend but reported zero impressions. Details are in [output/00_data_quality.csv](output/00_data_quality.csv).

Cleaning only catches rows that are impossible on their own, so `src/anomalies.py` also looks for days that are wrong compared with the weeks before: each paid channel's click-through rate, CPM and impressions per dollar against a 28-day rolling median and MAD. It finds all three problems I planted (the week of under-reported Meta clicks in March, the Display day with spend but no impressions, and LinkedIn's price jump in October) plus five one-day blips. It also caught a mistake of mine: my first cleaning rule capped impossible click counts at the impression count, which still left those rows at a 100% click rate. They're now re-estimated from the same ad's usual click rate.

All of this is from the generated data (seed 42), so the numbers are only as real as my assumptions. The SQL doesn't care where the data comes from, though. Real exports from Google Ads, Meta, GA4 and a CRM mapped to the same columns would work the same way.

## Models

### Attribution

The rule-based models above all pick a winner by position in the journey. I also wrote two data-driven ones: a Markov chain (how much do conversions drop if a channel is taken out of every journey) and Shapley values (each channel's average extra contribution across every combination of channels). Both are in `src/attribution.py` and only take a few dozen lines each, so I didn't pull in a library.

They mostly agree with each other, and both disagree with last touch in the same direction:

| Channel | Last touch | Markov | Shapley |
|---|---:|---:|---:|
| Google Search | 25.7% | 24.7% | 21.7% |
| Direct | 18.0% | 15.7% | 14.6% |
| Email | 17.4% | 13.9% | 14.2% |
| Organic Search | 11.3% | 13.2% | 12.1% |
| Meta | 5.1% | 10.4% | 10.0% |
| LinkedIn | 12.0% | 8.5% | 9.9% |
| Affiliate | 6.0% | 5.6% | 6.7% |
| Google Display | 1.3% | 4.7% | 5.7% |
| Referral | 3.1% | 2.6% | 3.5% |
| TikTok | 0.1% | 0.7% | 1.7% |

Meta roughly doubles its share and Display goes from almost nothing to about 5%. Email and Direct lose a few points each, because they tend to be the last click of a journey something else started. With the extra credit Display brings in roughly $25-30k against $33k of spend, close to breaking even in the first year, so it's less of a waste than last touch made it look. TikTok is still nowhere near. Meta is less clear cut too, and cutting it hard would probably cost more than last touch suggests.

### Lead scoring

`src/lead_scoring.py` predicts whether a new lead will end up paying, using only what's known when they fill in the form: channel, company size, pages viewed, the ad's offer, region, device and how many times they'd visited before. I validated it month by month (train on everything before July, test on July, and so on to October) so it never sees the future.

It's a modest model. AUC is 0.63, and plain logistic regression does just as well as XGBoost. That isn't surprising, since the only things in this data that actually drive conversion are channel, company size and engagement, and SHAP puts those three at the top with 84% of the weight. I tried industry, hour and weekday too and they made it slightly worse. It's still useful: the top 10% of scored leads convert at 15% against 7% overall, and the top 20% contain 39% of the people who went on to buy. If sales could only call back a fifth of new leads, that's the fifth to call.

### Marketing mix model

A single year of data isn't enough for an MMM, so `src/mmm.py` simulates three years of weekly spend and sign-ups for the five paid ad channels, with true effects I set in advance. Then it fits a model with carryover (adstock) and diminishing returns (a saturation curve) for each channel, plus trend and seasonality, and checks how close it gets to the truth. I fitted it with scipy and weak priors rather than a full Bayesian library, and used a block bootstrap for the uncertainty.

On a 13-week holdout it's off by 2.5% on average. Google Search comes back almost exactly (maximum effect 203 sign-ups a week against a true 210), and Meta's maximum effect is close (82 against 70). LinkedIn's carryover is underestimated, and the two small channels are where it struggles: Display and TikTok only add a handful of sign-ups a week next to noise of about 9, so the model gives them less credit than they deserve and the baseline soaks up the rest. 12 of the 15 true parameters land inside the 90% intervals.

What matters for budget decisions is the cost of the next sign-up at today's spend. The model has Search at $35, LinkedIn $48, Meta $82, and Display and TikTok somewhere around $370-400 (true values $120-146, but still the worst). The true marginal cost is inside the interval for all five channels.

### Budget

Keeping total spend the same and moving no channel more than 50% from where it is now, the optimiser moves money out of Meta, Display and TikTok and into Search and LinkedIn. The model says that's worth 7.7% more sign-ups a week. Scored against the true curves it's 5.4%. So the direction is right and the size is a bit optimistic, which is about what I'd expect to see with a real MMM too.

## Real data: the Hillstrom email test

Everything above runs on generated data, so I wanted at least one real campaign in here too. In 2008 Kevin Hillstrom published a test from an online retailer: 64,000 customers who had bought in the last year were randomly sent an email about men's merchandise, an email about women's merchandise, or nothing, and their site visits, purchases and spend were tracked for two weeks afterwards. `src/hillstrom.py` downloads the file from his site on the first run, checks it against a fixed checksum, loads it with `sql/real/01_hillstrom.sql`, and writes the `15_hillstrom_*` outputs.

Before looking at any results I checked the split. The three groups have 21,306, 21,307 and 21,387 customers (sample ratio test p = 0.90), and past spend, recency, new customers and purchase history all line up across them to within 0.01 standard deviations. So the comparison is fair.

Both emails worked, and all six effects survive a Holm correction:

| | No email | Men's email | Women's email |
|---|---:|---:|---:|
| Visited the site | 10.6% | 18.3% | 15.1% |
| Bought something | 0.57% | 1.25% | 0.88% |
| Spend per customer | $0.65 | $1.42 | $1.08 |

The men's email more than doubled purchases. The more useful finding is who each email works for. The women's email barely moved people who had only ever bought men's items (1.1 extra visits per 100, against about 7 for everyone else), while the men's email worked on all groups, including women-only buyers. Because of that, a rule that picks the email based on past purchases didn't beat simply sending everyone the men's email when I fitted it on half the customers and scored it on the other half.

Two things didn't help, and I've left them in because they're worth knowing. CUPED, which uses pre-test spend to cut noise, removed almost nothing (0.04% of the variance), because last year's spend barely predicts spend in a two-week window. And purchases are rare: with about 21,000 customers per group the test could only reliably detect a purchase-rate change of about 36% in relative terms. It was big enough for these effects, but a subtler email would have needed a much larger test.

The tests check the stats helpers against scipy and against data with a known answer, check that the sample ratio test catches a broken split, and check that the real results match the numbers usually reported for this dataset.

The data belongs to Kevin Hillstrom, who released it publicly through MineThatData for his 2008 data mining challenge. I don't store a copy in this repo; the script fetches it from his site.

## Agents

`src/agents/` has four LLM agents built on the Anthropic SDK, with no agent framework. They work on the same DuckDB database as everything else.

- The analyst answers a question in plain English by writing SQL. Its answer comes back as JSON where every number is a claim pointing at the query it came from, plus the column and row.
- The reviewer reads the question, the answer and the SQL behind it, and decides whether the query actually answers what was asked. It catches things like counting last touch when the question was about first touch.
- The data quality agent goes through the raw tables as they came in, before cleaning, and reports problems with row counts.
- The writer turns checked answers into a short brief.

What I cared about most was not letting a made-up number through. So none of the agents' numbers are trusted as written:

- The SQL tool only runs a single SELECT. sqlglot parses it first and rejects anything that writes, reads files, attaches databases or touches settings, and only known tables are allowed. Underneath that, DuckDB is opened read-only with external access off and its configuration locked, so a query that got past the parser still couldn't do anything. There's also a row cap and a 10 second timeout.
- Every query that runs gets an id. After the analyst answers, code re-runs the SQL for each claim and looks the number up in the fresh result. If a number doesn't match (allowing for rounding, or a share written as a percentage), or cites a query that never ran, the analyst gets the problems back and one more try.
- The data quality agent's row counts go through the same check.
- The writer only sees answers that passed both the code check and the reviewer. Afterwards every number in its text is pulled out and matched against the checked values, so it can't slip in a total it worked out itself.

`evals/golden.jsonl` has 32 questions, from "how much did we spend" to first-touch revenue and campaign-level cost per lead, each with a SQL query that gives the right answer. `evals/run_evals.py` runs the analyst on all of them and reports how many it gets right, plus how many passed every check but were still wrong. That second number is the one that matters, because those are the wrong answers someone would actually see. The eval needs an API key and costs a little to run, so the results aren't in the repo yet.

The tests in `tests/test_agents.py` don't call the API. A fake client plays back scripted model turns, which is enough to test the parts the safety depends on: the SQL guard (including going straight at the database connection), wrong numbers being caught and sent back, the reviewer rejecting a right number from the wrong query, and the writer being made to remove a number it invented.

## How it's put together

```
src/
  make_sample_data.py   generates the Lumora data, with planted data problems
  build_model.py        loads the raw CSVs into DuckDB and runs the model SQL
  run_analysis.py       runs everything below and writes output/
  attribution.py        Markov chain and Shapley attribution
  lead_scoring.py       XGBoost and logistic regression lead scoring
  mmm.py                marketing mix model and budget optimiser
  anomalies.py          flags days where a channel's numbers look wrong
  hillstrom.py          the real email experiment
  build_site.py         bundles the outputs into one JSON file for the site
  agent_cli.py          runs the agents from the command line
  agents/               analyst, reviewer, data quality and writer agents, plus the SQL guard and number checks
sql/
  model/                staging (cleaning) and the star schema
  analysis/             the ten analysis queries
  real/                 loading and cleaning the Hillstrom data
evals/                  32 golden questions and the eval runner for the analyst agent
tests/                  59 tests: pipeline, models, agents, anomalies and the experiment stats
site/                   the dashboard: index.html, style.css, app.js
output/                 every result as CSV, plus marketing_report.xlsx
docs/                   notes on the plan and real data sources, and a data dictionary
.github/workflows/      ci.yml runs lint and tests, pages.yml rebuilds and publishes the site
Makefile                shortcuts for the commands under "Running it"
```

Raw CSVs go into DuckDB, get cleaned in `sql/model/01_staging.sql`, and end up as a small star schema in `sql/model/02_marts.sql` (every column is described in [docs/data-dictionary.md](docs/data-dictionary.md)):

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

The models live in `src/`: `attribution.py` (11_ outputs), `lead_scoring.py` (12_), `mmm.py` (13_ and 14_ for the budget split) and `hillstrom.py` (15_, the real email test).

## Running it

You'll need Python 3.12 or newer (CI runs on 3.12).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python src/make_sample_data.py
python src/run_analysis.py
python -m pytest -q tests
```

The agents need an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=...
python src/agent_cli.py ask "Which channel had the lowest cost per customer?"
python src/agent_cli.py quality
python src/agent_cli.py brief
python evals/run_evals.py
```

The `ask`, `quality` and `brief` commands save what they produce to `output/agents/`, and the eval writes `evals/results/latest.csv`.

There's also a Makefile with the same steps: `make setup`, then `make all` runs data, analysis, lint, tests and the site data in one go (`make help` lists the rest).

Results go to `output/`, one CSV per query or model output plus an Excel file with everything in it. The whole thing takes about 20 seconds after the first run, which also downloads the 4 MB Hillstrom file. Add `--skip-models` to only run the SQL, or `--skip-real` to leave out the real dataset. The tests check things like the funnel never getting bigger, spend totals matching, attribution credit adding up to one per lead, the Shapley code against small cases worked out by hand, the lead model not using anything from after the form was filled in, and the MMM getting the biggest channel's effect back within 15%.

## The site

`site/` is a plain static page: HTML, CSS and one JavaScript file that draws the charts as SVG, with no libraries. `src/build_site.py` bundles the outputs into `site/data/site.json`, and a GitHub Actions workflow regenerates the data, reruns everything and publishes the page on every push. To look at it locally:

```bash
python src/build_site.py
python -m http.server 8000 --directory site
```

## What's next

The next step is running the agent eval with a real API key and putting the score here. After that, roughly in order: a Bayesian version of the mix model to compare against mine, daily KPI forecasts with anomaly flags, a geo-lift test, the GA4 sample as a second real dataset, and moving the SQL models to dbt with tests. My notes on the plan and on getting real data are in [docs/](docs/).
