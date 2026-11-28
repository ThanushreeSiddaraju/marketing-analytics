"""The forecasting methods on series with a known answer, and the back-test on the sample data."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import forecast  # noqa: E402
from build_model import build  # noqa: E402

WEEK = np.array([20, 30, 30, 30, 30, 25, 15], dtype=float)


def test_same_day_last_week_repeats_the_last_week():
    y = np.tile(WEEK, 4)
    assert forecast.same_day_last_week(y, 10).tolist() == np.tile(WEEK, 2)[:10].tolist()


def test_weekday_average_averages_matching_days():
    y = np.concatenate([WEEK, WEEK + 4, WEEK, WEEK + 4])
    assert forecast.weekday_average(y, 7) == pytest.approx(WEEK + 2)


def test_holt_winters_learns_a_weekly_pattern_with_a_trend():
    rng = np.random.default_rng(0)
    t = np.arange(140)
    y = np.tile(WEEK, 20) + 0.05 * t + rng.normal(0, 0.5, 140)
    fc = forecast.holt_winters(y, 14)
    truth = np.tile(WEEK, 2) + 0.05 * np.arange(140, 154)
    assert np.abs(fc - truth).mean() < 1.0


@pytest.fixture(scope="module")
def res(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fc")
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(tmp / "raw")],
                   check=True, capture_output=True)
    build(tmp / "raw", tmp / "f.duckdb")
    return forecast.run(tmp / "f.duckdb")


def test_backtest_picks_the_most_accurate_method(res):
    bt = res["17_forecast_backtest"]
    assert len(bt) == len(forecast.METHODS)
    assert bt.mae.is_monotonic_increasing
    assert res["17_forecast_next"].method.iloc[0] == bt.method.iloc[0]
    # ranges are built from back-test errors, so they should hold roughly 80% of actuals
    assert bt.inside_80pct_range.between(0.65, 0.95).all()


def test_forecast_has_sane_ranges(res):
    nxt = res["17_forecast_next"]
    assert len(nxt) == forecast.AHEAD
    assert (nxt.low_80 <= nxt.forecast).all() and (nxt.forecast <= nxt.high_80).all()
    assert (nxt.low_80 >= 0).all()
    assert pd.to_datetime(nxt.date).min() == pd.Timestamp("2026-01-01")


def test_weekly_view_uses_whole_weeks(res):
    w = res["17_forecast_weekly"]
    actual = w.dropna(subset=["actual"])
    # the last actual week ends on the last day of data and isn't a stub
    assert actual.week_ending.iloc[-1] == pd.Timestamp("2025-12-31").date()
    assert actual.actual.iloc[-1] > 0.6 * actual.actual.iloc[:-1].mean()
