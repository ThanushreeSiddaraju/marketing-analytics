"""Forecast daily leads, and check the forecast against simple baselines first.

Three methods:
  same day last week     tomorrow looks like the same weekday a week ago
  weekday average        the average of the last four of that weekday
  Holt-Winters           level, trend and a weekly pattern, smoothed
                         (additive, parameters fitted by least squares)

Each one is back-tested the way it would actually be used: from 26 weekly starting
points over the second half of the year, forecast the next 14 days using only
the data up to that point, then compare with what happened. The method with
the lowest average error forecasts January, with an 80% range taken from how
wrong the back-tests were at each horizon, so the range is earned rather than
assumed.

Outputs (output/):
  17_forecast_backtest.csv   error by method (MAE, MAPE, how often the actual fell inside the range)
  17_forecast_next.csv       daily forecast for the next 28 days with an 80% range
  17_forecast_weekly.csv     weekly actuals and forecast, for the chart

Usage:  python src/forecast.py [--db data/marketing.duckdb] [--out output]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
SEASON = 7
HORIZON = 14
ORIGINS = 26
AHEAD = 28


def daily_leads(db: Path) -> pd.Series:
    con = duckdb.connect(str(db), read_only=True)
    try:
        df = con.execute("""
            SELECT d.date, COUNT(l.lead_id) AS leads
            FROM dim_date d LEFT JOIN fact_leads l ON l.created_at::DATE = d.date
            GROUP BY 1 ORDER BY 1""").df()
    finally:
        con.close()
    return df.set_index(pd.to_datetime(df.date)).leads.astype(float)


# ---------------------------------------------------------------- methods

def same_day_last_week(y: np.ndarray, h: int) -> np.ndarray:
    last = y[-SEASON:]
    return np.array([last[i % SEASON] for i in range(h)])


def weekday_average(y: np.ndarray, h: int, weeks: int = 4) -> np.ndarray:
    block = y[-SEASON * weeks:].reshape(weeks, SEASON).mean(axis=0)
    return np.array([block[i % SEASON] for i in range(h)])


def _hw_run(y, alpha, beta, gamma):
    m = SEASON
    level = y[:m].mean()
    trend = (y[m:2 * m].mean() - y[:m].mean()) / m
    season = list(y[:m] - level)
    sse = 0.0
    for t in range(m, len(y)):
        s = season[t - m]
        pred = level + trend + s
        sse += (y[t] - pred) ** 2
        new_level = alpha * (y[t] - s) + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        season.append(gamma * (y[t] - new_level) + (1 - gamma) * s)
        level = new_level
    return sse, level, trend, season


def holt_winters(y: np.ndarray, h: int) -> np.ndarray:
    res = minimize(lambda p: _hw_run(y, *p)[0], x0=[0.2, 0.02, 0.1],
                   bounds=[(0.01, 0.99), (0.0, 0.3), (0.0, 0.99)], method="L-BFGS-B")
    _, level, trend, season = _hw_run(y, *res.x)
    n = len(y)
    return np.array([level + (i + 1) * trend + season[n - SEASON + (i % SEASON)] for i in range(h)])


METHODS = {"same day last week": same_day_last_week, "weekday average": weekday_average, "Holt-Winters": holt_winters}


# ---------------------------------------------------------------- back-test

def backtest(y: pd.Series) -> pd.DataFrame:
    """One row per method, origin and horizon step with the forecast and the actual."""
    v = y.to_numpy()
    last_origin = len(v) - HORIZON
    origins = [last_origin - SEASON * k for k in range(ORIGINS)][::-1]
    rows = []
    for name, fn in METHODS.items():
        for o in origins:
            fc = fn(v[:o], HORIZON)
            for step in range(HORIZON):
                rows.append(dict(method=name, origin=y.index[o].date(), step=step + 1,
                                 forecast=fc[step], actual=v[o + step]))
    return pd.DataFrame(rows)


def score(bt: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    bt = bt.assign(error=bt.actual - bt.forecast)
    # 80% range per method and horizon step, from the back-test errors themselves
    bands = {m: g.groupby("step").error.quantile([0.1, 0.9]).unstack() for m, g in bt.groupby("method")}
    # the same for whole weeks: daily errors partly cancel, so a weekly range isn't seven daily ones added up
    wk = bt.assign(week=(bt.step - 1) // SEASON + 1).groupby(["method", "origin", "week"]).error.sum().reset_index()
    week_bands = {m: g.groupby("week").error.quantile([0.1, 0.9]).unstack() for m, g in wk.groupby("method")}
    out = []
    for m, g in bt.groupby("method"):
        b = bands[m]
        lo = g.forecast + g.step.map(b[0.1])
        hi = g.forecast + g.step.map(b[0.9])
        out.append(dict(method=m, mae=g.error.abs().mean(), mape=(g.error.abs() / g.actual).mean(),
                        bias=g.error.mean(), inside_80pct_range=((g.actual >= lo) & (g.actual <= hi)).mean(),
                        forecasts=len(g)))
    return pd.DataFrame(out).sort_values("mae").reset_index(drop=True), bands, week_bands


def run(db: Path) -> dict[str, pd.DataFrame]:
    y = daily_leads(db)
    scores, bands, week_bands = score(backtest(y))
    best = scores.method.iloc[0]
    fc = METHODS[best](y.to_numpy(), AHEAD)
    b = bands[best]
    step = np.minimum(np.arange(1, AHEAD + 1), HORIZON)  # past the back-tested horizon, reuse the widest step
    dates = pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=AHEAD, freq="D")
    nxt = pd.DataFrame({"date": dates.date, "method": best, "forecast": fc,
                        "low_80": fc + b.loc[step, 0.1].to_numpy(), "high_80": fc + b.loc[step, 0.9].to_numpy()})
    nxt[["forecast", "low_80", "high_80"]] = nxt[["forecast", "low_80", "high_80"]].clip(lower=0)

    # weeks end on the last day of data, so the last actual week and every forecast week are whole
    rule = "W-" + y.index[-1].strftime("%a").upper()
    weekly_actual = y.resample(rule).sum().iloc[-26:]
    f = nxt.set_index(pd.to_datetime(nxt.date)).forecast.resample(rule).sum()
    wb = week_bands[best]
    wsteps = np.minimum(np.arange(1, len(f) + 1), wb.index.max())
    weekly = pd.concat([
        pd.DataFrame({"week_ending": weekly_actual.index.date, "actual": weekly_actual.to_numpy()}),
        pd.DataFrame({"week_ending": f.index.date, "forecast": f.to_numpy(),
                      "low_80": (f.to_numpy() + wb.loc[wsteps, 0.1].to_numpy()).clip(min=0),
                      "high_80": f.to_numpy() + wb.loc[wsteps, 0.9].to_numpy()}),
    ], ignore_index=True)
    return {"17_forecast_backtest": scores.round(4), "17_forecast_next": nxt.round(2), "17_forecast_weekly": weekly.round(1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.db)
    for name, df in res.items():
        df.to_csv(args.out / f"{name}.csv", index=False)
    print(res["17_forecast_backtest"].to_string(index=False))
    print(res["17_forecast_weekly"].tail(6).to_string(index=False))


if __name__ == "__main__":
    main()
