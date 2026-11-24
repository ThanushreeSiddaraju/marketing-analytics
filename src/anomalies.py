"""Flag days where a channel's ad numbers look wrong.

For each paid channel and day it compares click-through rate, CPM and
impressions per dollar with the median of the previous 28 days, scaled by the
median absolute deviation (MAD). Medians are used instead of means so one bad
day doesn't drag the baseline with it. A day is flagged when it's more than
4 robust standard deviations away. Spend that was billed with no impressions
at all is always flagged.

Consecutive flagged days for the same channel and metric are grouped into
episodes, because a tracking outage that lasts a week is one problem, not
seven.

This is deliberately simple. It's the sanity baseline I'd want running before
anything fancier like a forecasting model, and the planted problems in the
sample data give it something to be checked against.

Outputs (output/):
  16_anomaly_days.csv       every flagged channel-day and metric
  16_anomaly_episodes.csv   flagged days grouped into runs

Usage:  python src/anomalies.py [--db data/marketing.duckdb] [--out output]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WINDOW = 28
MIN_HISTORY = 14
THRESHOLD = 4.0
METRICS = {"ctr": "click-through rate", "cpm": "cost per 1,000 impressions", "impr_per_dollar": "impressions per dollar"}


def daily(db: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("""
            SELECT a.date, a.channel,
                   SUM(a.spend)::DOUBLE AS spend, SUM(a.impressions) AS impressions, SUM(a.clicks) AS clicks
            FROM fact_ad_daily a JOIN dim_channel c USING (channel)
            WHERE c.channel_type = 'Paid'
            GROUP BY 1, 2 ORDER BY 2, 1
        """).df()
    finally:
        con.close()


def robust_scores(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Expected value and robust z-score against the trailing window (today excluded)."""
    past = s.shift(1).rolling(WINDOW, min_periods=MIN_HISTORY)
    med = past.median()
    mad = (s.shift(1) - med).abs().rolling(WINDOW, min_periods=MIN_HISTORY).median()
    scale = 1.4826 * mad.clip(lower=0.02 * med.abs())  # floor so a very steady series doesn't flag tiny wiggles
    return med, (s - med) / scale


def flag(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ctr"] = np.where(df.impressions > 0, df.clicks / df.impressions.where(df.impressions > 0), np.nan)
    df["cpm"] = np.where(df.impressions > 0, df.spend / df.impressions.where(df.impressions > 0) * 1000, np.nan)
    df["impr_per_dollar"] = np.where(df.spend > 0, df.impressions / df.spend.where(df.spend > 0), np.nan)
    rows = []
    for ch, g in df.groupby("channel"):
        g = g.set_index("date").sort_index()
        for m in METRICS:
            # a day with spend but no impressions breaks the ratios, so leave it out of the baseline
            clean = g[m].where(~((g.spend > 0) & (g.impressions == 0)))
            expected, z = robust_scores(clean)
            hit = z.abs() > THRESHOLD
            for d in g.index[hit.fillna(False)]:
                rows.append(dict(date=d, channel=ch, metric=m, value=g.at[d, m], expected=expected[d], robust_z=z[d]))
        for d in g.index[(g.spend > 0) & (g.impressions == 0)]:
            rows.append(dict(date=d, channel=ch, metric="impr_per_dollar", value=0.0, expected=np.nan, robust_z=-np.inf))
    out = pd.DataFrame(rows, columns=["date", "channel", "metric", "value", "expected", "robust_z"])
    out["direction"] = np.where(out.robust_z > 0, "high", "low")
    out["label"] = out.metric.map(METRICS)
    return out.drop_duplicates(["date", "channel", "metric"]).sort_values(["date", "channel", "metric"]).reset_index(drop=True)


def episodes(days: pd.DataFrame) -> pd.DataFrame:
    if days.empty:
        return pd.DataFrame(columns=["channel", "metric", "label", "direction", "start", "end", "days", "worst_z"])
    d = days.sort_values(["channel", "metric", "direction", "date"]).copy()
    gap = d.groupby(["channel", "metric", "direction"]).date.diff().dt.days.ne(1)
    d["run"] = gap.cumsum()
    ep = d.groupby("run").agg(channel=("channel", "first"), metric=("metric", "first"), label=("label", "first"),
                              direction=("direction", "first"), start=("date", "min"), end=("date", "max"),
                              days=("date", "size"),
                              worst_z=("robust_z", lambda z: z[np.isfinite(z)].abs().max() if np.isfinite(z).any() else np.inf))
    return ep.sort_values(["start", "channel"]).reset_index(drop=True)


def run(db: Path) -> dict[str, pd.DataFrame]:
    days = flag(daily(db))
    ep = episodes(days)
    return {"16_anomaly_days": days.round({"value": 4, "expected": 4, "robust_z": 2}),
            "16_anomaly_episodes": ep.round({"worst_z": 2})}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.db)
    for name, df in res.items():
        df.to_csv(args.out / f"{name}.csv", index=False)
    print(res["16_anomaly_episodes"].to_string(index=False))


if __name__ == "__main__":
    main()
