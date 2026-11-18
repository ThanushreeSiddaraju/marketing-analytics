# Plan

Rough order I'm working in. The SQL, the first round of models and the agents are done.

## Modelling

Done:

- Markov chain and Shapley attribution. I wrote these myself instead of using a library. It isn't much code for 10 channels, and the maintained Python package is GPL.
- Lead scoring with XGBoost and logistic regression, SHAP for the drivers, calibration and lift by decile.
- Marketing mix model on three years of simulated weekly data with known true effects, so I can check what it recovers. I went with scipy and weak priors instead of PyMC-Marketing for now. It runs in about 10 seconds, which keeps CI quick.
- A budget optimiser on top of the MMM response curves.

Still to do:

- A proper Bayesian version of the MMM (PyMC-Marketing) to compare against, since my bootstrap intervals are a bit too narrow.
- Forecast and anomaly flags on daily KPIs with statsforecast, plus a simple median/MAD check as a sanity baseline.
- An A/B test write-up (power, sample ratio check, CUPED) and a geo-lift test with CausalPy.

## Agents

Built, in src/agents/, on the Anthropic SDK directly without a framework:

- data quality: looks at the raw tables and reports what's wrong, with row counts that get checked
- analyst: answers questions by writing SQL against a locked-down read-only connection
- reviewer: checks that the SQL answers the question that was asked
- writer: turns checked answers into a short brief, and its numbers get traced back too

Every number cites a query id and is re-checked in code rather than by another model. The SQL tool only allows a single SELECT, with a row limit and a timeout, and external access is off in DuckDB as well.

Still to do: run the 32-question eval with a real key and write up the score, then score the data quality agent on how many of the planted problems it finds with the right counts.

## Site

A static site on GitHub Pages, rebuilt by GitHub Actions. Charts read precomputed JSON. If I add a "ask the data" box later it'll need a small serverless function to hold the API key.

## Also want to add

- dbt models with tests
- schema checks at the point raw data comes in
- one real dataset alongside the generated one (see data-sources.md)
