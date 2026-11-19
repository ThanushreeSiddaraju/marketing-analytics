"""Checks on the experiment statistics, plus the real Hillstrom results.

The stats helpers are tested against scipy and against data where the answer
is known. The real-data tests run when the CSV has been downloaded (the
pipeline and CI do that) and are skipped otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hillstrom  # noqa: E402


def test_diff_ci_matches_welch_t_test():
    rng = np.random.default_rng(1)
    t, c = rng.normal(1.2, 2, 3000), rng.normal(1.0, 1.5, 2500)
    r = hillstrom.diff_ci(t, c)
    ref = stats.ttest_ind(t, c, equal_var=False)
    assert r["p_value"] == pytest.approx(ref.pvalue, rel=1e-6)
    assert r["ci_low"] < r["lift"] < r["ci_high"]
    assert r["lift"] == pytest.approx(t.mean() - c.mean())


def test_holm_adjustment():
    p = pd.Series([0.01, 0.04, 0.03, 0.005])
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1 -> max(0.06, 0.04)=0.06
    assert hillstrom.holm(p).tolist() == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_cuped_shrinks_variance_when_the_covariate_predicts_the_outcome():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, 5000)
    y = 3 * x + rng.normal(0, 1, 5000)
    adj = hillstrom.cuped(y, x)
    assert adj.var() < 0.15 * y.var()
    assert adj.mean() == pytest.approx(y.mean())


def fake_experiment(n=30000, lift=0.05, seed=3):
    rng = np.random.default_rng(seed)
    arm = rng.choice(["control", "mens_email", "womens_email"], n)
    base = 0.10 + lift * (arm != "control")
    visited = rng.random(n) < base
    converted = visited & (rng.random(n) < 0.06)
    return pd.DataFrame({
        "arm": arm, "visited": visited, "converted": converted,
        "spend": np.where(converted, rng.gamma(2, 50, n), 0.0),
        "months_since_purchase": rng.integers(1, 13, n), "spend_last_year": rng.gamma(2, 120, n),
        "new_customer": rng.random(n) < 0.5, "bought_mens": rng.random(n) < 0.55, "bought_womens": rng.random(n) < 0.55,
    })


def test_effects_recover_a_known_lift():
    eff = hillstrom.effects(fake_experiment()).set_index(["arm", "metric"])
    for a in hillstrom.ARMS:
        r = eff.loc[(a, "visited")]
        assert r.ci_low < 0.05 < r.ci_high and r.significant


def test_sample_ratio_check_catches_a_broken_split():
    df = fake_experiment()
    broken = pd.concat([df, df[df.arm == "mens_email"].head(1500)])
    p_ok = hillstrom.balance(df).query("check.str.startswith('sample ratio')").value.iloc[0]
    p_bad = hillstrom.balance(broken).query("check.str.startswith('sample ratio')").value.iloc[0]
    assert p_ok > 0.01 and p_bad < 0.001


# ---------------------------------------------------------------- the real data

needs_data = pytest.mark.skipif(not hillstrom.CSV.exists(), reason="Hillstrom CSV not downloaded")


@pytest.fixture(scope="module")
def real():
    return hillstrom.run(hillstrom.CSV)


@needs_data
def test_real_data_loads_cleanly():
    df = hillstrom.load(hillstrom.CSV)
    assert len(df) == 64000
    assert set(df.arm) == {"control", "mens_email", "womens_email"}
    assert set(df.area) == {"rural", "suburban", "urban"}
    assert df.converted.le(df.visited).all()  # nobody bought without visiting
    assert (df.spend[~df.converted] == 0).all()


@needs_data
def test_real_split_is_balanced(real):
    b = real["15_hillstrom_balance"]
    assert b.query("check.str.startswith('sample ratio')").value.iloc[0] > 0.01
    assert b[b.check.str.startswith("balance")].value.abs().max() < 0.05


@needs_data
def test_real_effects_match_the_published_numbers(real):
    eff = real["15_hillstrom_effects"].set_index(["arm", "metric"])
    # widely reported results for this dataset
    assert eff.loc[("mens_email", "visited"), "treated"] == pytest.approx(0.1828, abs=5e-4)
    assert eff.loc[("mens_email", "visited"), "control"] == pytest.approx(0.1062, abs=5e-4)
    assert eff.loc[("womens_email", "visited"), "treated"] == pytest.approx(0.1514, abs=5e-4)
    assert eff.loc[("mens_email", "spend"), "lift"] == pytest.approx(0.77, abs=0.01)
    assert eff.significant.all()
