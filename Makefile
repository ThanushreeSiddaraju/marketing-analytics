# Shortcuts for the usual commands. Run `make` to see them.
PY ?= .venv/bin/python

.PHONY: help setup data analysis test lint site serve eval all

help:
	@echo "make setup     create .venv and install requirements"
	@echo "make data      generate the sample data (seed 42)"
	@echo "make analysis  build the model and run every query and model (downloads the real dataset once)"
	@echo "make test      run the tests"
	@echo "make lint      run ruff"
	@echo "make site      build the site data"
	@echo "make serve     serve the site on http://localhost:8000"
	@echo "make eval      score the analyst agent (needs ANTHROPIC_API_KEY)"
	@echo "make all       data, analysis, lint, test and site in one go"

setup:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt ruff

data:
	$(PY) src/make_sample_data.py

analysis:
	$(PY) src/run_analysis.py

test:
	$(PY) -m pytest -q tests

lint:
	$(PY) -m ruff check .

site:
	$(PY) src/build_site.py

serve: site
	$(PY) -m http.server 8000 --directory site

eval:
	$(PY) evals/run_evals.py

all: data analysis lint test site
