"""Checks on the attribution, lead scoring and MMM code.

The small hand-made journeys have answers you can work out on paper, so they
catch maths mistakes. The rest run on the generated data.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import attribution  # noqa: E402
import lead_scoring  # noqa: E402
import mmm  # noqa: E402
from build_model import build  # noqa: E402


def journeys(rows):
    return pd.DataFrame(rows, columns=["path", "converted", "revenue"])


# ---------------------------------------------------------------- attribution, toy cases

def test_single_channel_journeys_keep_their_own_credit():
    j = journeys([(["A"], True, 10.0), (["A"], False, 0.0), (["B"], True, 30.0), (["B"], True, 20.0)])
    for fn in (attribution.markov_attribution, attribution.shapley_attribution):
        assert fn(j).to_dict() == pytest.approx({"A": 1, "B": 2})
        assert fn(j, "revenue").to_dict() == pytest.approx({"A": 10, "B": 50})


def test_shapley_splits_a_shared_journey_evenly():
    j = journeys([(["A", "B"], True, 100.0)])
    assert attribution.shapley_attribution(j, "revenue").to_dict() == pytest.approx({"A": 50, "B": 50})


def test_shapley_matches_hand_calculation():
    # v({A})=1, v({B})=0, v({A,B})=3  ->  phi_A = (1 + 3)/2 = 2, phi_B = (0 + 2)/2 = 1
    j = journeys([(["A"], True, 0.0), (["A", "B"], True, 0.0), (["B", "A"], True, 0.0), (["B"], False, 0.0)])
    assert attribution.shapley_attribution(j).to_dict() == pytest.approx({"A": 2, "B": 1})


def test_markov_gives_nothing_to_a_channel_that_never_helps():
    # C only ever shows up on journeys that don't convert
    j = journeys([(["A"], True, 1.0), (["A", "C"], False, 0.0), (["C"], False, 0.0), (["B", "A"], True, 1.0)])
    credit = attribution.markov_attribution(j)
    assert credit["C"] == pytest.approx(0, abs=1e-9)
    assert credit.sum() == pytest.approx(2)


# ---------------------------------------------------------------- on the generated data

@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("models")
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(tmp / "raw")],
                   check=True, capture_output=True)
    build(tmp / "raw", tmp / "m.duckdb")
    return tmp / "m.duckdb"


def test_attribution_models_agree_on_totals(db):
    j = attribution.load_journeys(db)
    res = attribution.compare(j)
    for model, g in res.groupby("model"):
        assert g.customers.sum() == pytest.approx(j.converted.sum(), rel=1e-3), model
        assert g.revenue.sum() == pytest.approx(j.loc[j.converted, "revenue"].sum(), rel=1e-3), model
        assert (g.revenue >= 0).all(), model


def test_rule_based_python_matches_sql(db):
    from run_analysis import run_queries
    sql = run_queries(db)["08_attribution_rules"].set_index(["model", "channel"]).revenue_share
    py = attribution.compare(attribution.load_journeys(db)).set_index(["model", "channel"]).revenue_share
    common = sql.index.intersection(py.index)
    assert len(common) == 40
    assert (sql[common] - py[common]).abs().max() < 1e-3


def test_lead_scoring_beats_random_without_leaking(db):
    assert not {"mql_at", "sql_at", "won_at", "is_mql", "is_sql", "plan", "mrr"} & set(
        lead_scoring.CATEGORICAL + lead_scoring.NUMERIC)
    res = lead_scoring.run(db)
    pooled = res["12_lead_scoring_metrics"].query("test_month == 'all'").set_index("model")
    assert pooled.roc_auc.min() > 0.58
    dec = res["12_lead_score_deciles"]
    assert dec.lift.iloc[0] > 1.5
    assert dec.customers.sum() == pooled.customers.iloc[0]
    top3 = set(res["12_lead_score_drivers"].feature.head(3))
    assert top3 == {"channel", "company_size", "landing_pageviews"}


# ---------------------------------------------------------------- MMM

def test_adstock_and_hill():
    assert mmm.adstock(np.array([10.0, 0, 0]), 0.5).tolist() == [10, 5, 2.5]
    assert mmm.hill(np.array([100.0]), 100, 8)[0] == pytest.approx(4)


@pytest.fixture(scope="module")
def mmm_res():
    return mmm.run(seed=7, n_boot=30)


def test_mmm_fits_and_recovers_the_biggest_channel(mmm_res):
    fit = mmm_res["13_mmm_fit"].iloc[0]
    assert fit.r2_in_sample > 0.8 and fit.holdout_mape < 0.06
    rec = mmm_res["13_mmm_parameter_recovery"].set_index(["channel", "parameter"])
    beta = rec.loc[("Google Search", "beta")]
    assert abs(beta.estimate / beta.true - 1) < 0.15
    ch = mmm_res["13_mmm_channels"].set_index("channel")
    # the order of marginal cost should match the truth for the three big channels
    big = ["Google Search", "LinkedIn Ads", "Meta Ads"]
    assert list(ch.loc[big].marginal_cost_per_signup.sort_values().index) == \
        list(ch.loc[big].true_marginal_cost_per_signup.sort_values().index)


def test_budget_keeps_total_and_actually_helps(mmm_res):
    b = mmm_res["14_budget_allocation"].set_index("channel")
    ch = b.drop("Total")
    assert ch.recommended_weekly_spend.sum() == pytest.approx(ch.current_weekly_spend.sum(), rel=1e-3)
    assert (ch.change_pct.abs() <= 50.1).all()
    assert b.loc["Total", "signups_after_true"] > b.loc["Total", "signups_now_true"]
