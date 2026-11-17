# Plan

Rough order I'm working in. The SQL part and the first round of models are done.

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

Four to start, written against the Anthropic SDK directly, without a framework:

- data quality: looks at the raw tables and explains what's wrong
- analyst: answers questions by writing SQL against a read-only copy of the database
- reviewer: re-runs the query behind every number the other agents state and rejects anything that doesn't match
- writer: turns the checked findings into short summaries for the site

The SQL tool only allows a single SELECT, with a row limit and a timeout, and external access is turned off in DuckDB. I'll keep a set of around 40 questions with known answers to measure how often the analyst gets them right.

## Site

A static site on GitHub Pages, rebuilt by GitHub Actions. Charts read precomputed JSON. If I add a "ask the data" box later it'll need a small serverless function to hold the API key.

## Also want to add

- dbt models with tests
- schema checks at the point raw data comes in
- one real dataset alongside the generated one (see data-sources.md)
