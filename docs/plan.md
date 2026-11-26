# Plan

Rough order I'm working in. The SQL, the first round of models, the agents, the site and one real dataset are done.

## Modelling

Done:

- Markov chain and Shapley attribution. I wrote these myself instead of using a library. It isn't much code for 10 channels, and the maintained Python package is GPL.
- Lead scoring with XGBoost and logistic regression, SHAP for the drivers, calibration and lift by decile.
- Marketing mix model on three years of simulated weekly data with known true effects, so I can check what it recovers. I went with scipy and weak priors instead of PyMC-Marketing for now. It runs in about 10 seconds, which keeps CI quick.
- A budget optimiser on top of the MMM response curves.

Still to do:

- A proper Bayesian version of the MMM (PyMC-Marketing) to compare against, since my bootstrap intervals are a bit too narrow.
- Forecast and anomaly flags on daily KPIs with statsforecast, plus a simple median/MAD check as a sanity baseline.
- A geo-lift test with CausalPy. (The A/B test part is done, on the real Hillstrom data: sample ratio check, balance, Holm-corrected effects, CUPED, power and a held-out targeting check.)

## Agents

Built, in src/agents/, on the Anthropic SDK directly without a framework:

- data quality: looks at the raw tables and reports what's wrong, with row counts that get checked
- analyst: answers questions by writing SQL against a locked-down read-only connection
- reviewer: checks that the SQL answers the question that was asked
- writer: turns checked answers into a short brief, and its numbers get traced back too

Every number cites a query id and is re-checked in code rather than by another model. The SQL tool only allows a single SELECT, with a row limit and a timeout, and external access is off in DuckDB as well.

Still to do: run the 32-question eval with a real key and write up the score, then score the data quality agent on how many of the planted problems it finds with the right counts.

## Site

Done: a static page on GitHub Pages, rebuilt by GitHub Actions on every push. The charts are hand-written SVG reading one JSON file. If I add an "ask the data" box later it'll need a small serverless function to hold the API key, because a static page can't keep one secret.

## Also want to add

- dbt models with tests
- ~~schema checks at the point raw data comes in~~ done, in `src/contracts.py`
- a second real dataset with ads and sessions in it, probably the GA4 sample (the Hillstrom email test is in, see data-sources.md)
