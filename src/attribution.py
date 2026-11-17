"""Data-driven attribution: Markov chain removal effect and Shapley values.

Both use the lead journeys in fact_journeys (every visit a lead made up to the
moment they filled in the form). A journey "converts" if that lead later became
a paying customer. Results are compared with the rule-based models from
sql/analysis/08_attribution_rules.sql.

Usage:  python src/attribution.py [--db data/marketing.duckdb] [--out output]
"""
from __future__ import annotations

import argparse
from math import factorial
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_journeys(db: Path) -> pd.DataFrame:
    """One row per lead: ordered list of channels, converted flag and revenue."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("""
            SELECT lead_id,
                   list(channel ORDER BY touch_number) AS path,
                   any_value(is_customer) AS converted,
                   any_value(revenue) AS revenue
            FROM fact_journeys
            GROUP BY lead_id
        """).df()
    finally:
        con.close()


# ---------------------------------------------------------------- Markov

def _conversion_probability(P: np.ndarray, start: int, conv: int, transient: list[int]) -> float:
    """P(absorbed in `conv` | start) for an absorbing chain with transition matrix P."""
    Q = P[np.ix_(transient, transient)]
    R = P[transient, conv]
    # Solve (I - Q) x = R; x[i] is the chance of eventually converting from state i.
    x = np.linalg.solve(np.eye(len(transient)) - Q, R)
    return float(x[transient.index(start)])


def markov_attribution(journeys: pd.DataFrame, weight: str | None = None) -> pd.Series:
    """First-order Markov removal effect. Returns credit per channel that sums to
    the number of converted journeys, or to the total of `weight` (e.g. revenue)."""
    channels = sorted({c for p in journeys.path for c in p})
    states = ["(start)", *channels, "(conversion)", "(null)"]
    idx = {s: i for i, s in enumerate(states)}
    n = len(states)

    counts = np.zeros((n, n))
    for path, conv in zip(journeys.path, journeys.converted):
        seq = ["(start)", *path, "(conversion)" if conv else "(null)"]
        for a, b in zip(seq, seq[1:]):
            counts[idx[a], idx[b]] += 1
    counts[idx["(conversion)"], idx["(conversion)"]] = 1
    counts[idx["(null)"], idx["(null)"]] = 1
    P = counts / counts.sum(axis=1, keepdims=True)

    start, conv, null = idx["(start)"], idx["(conversion)"], idx["(null)"]
    transient = [idx["(start)"]] + [idx[c] for c in channels]
    base = _conversion_probability(P, start, conv, transient)

    removal = {}
    for c in channels:
        Pr = P.copy()
        k = idx[c]
        # Anyone who would have moved to the removed channel drops out instead.
        Pr[:, null] += Pr[:, k]
        Pr[:, k] = 0
        Pr[k, :] = 0
        Pr[k, null] = 1
        removal[c] = 1 - _conversion_probability(Pr, start, conv, transient) / base

    effect = pd.Series(removal).clip(lower=0)
    # Hand each converting journey's value to the channels on that journey,
    # in proportion to their removal effects. Credit then sums to the total
    # number of customers (or revenue) and high-value journeys count for more.
    credit = pd.Series(0.0, index=channels)
    conv_j = journeys[journeys.converted]
    vals = conv_j[weight] if weight else pd.Series(1.0, index=conv_j.index)
    for path, val in zip(conv_j.path, vals):
        on_path = list(dict.fromkeys(path))
        re = effect[on_path]
        credit[on_path] += val * (re / re.sum() if re.sum() > 0 else 1 / len(on_path))
    return credit


# ---------------------------------------------------------------- Shapley

def shapley_attribution(journeys: pd.DataFrame, weight: str | None = None) -> pd.Series:
    """Exact Shapley values where a coalition S is worth the conversions (or
    revenue) from journeys that only touched channels in S."""
    channels = sorted({c for p in journeys.path for c in p})
    n = len(channels)
    bit = {c: 1 << i for i, c in enumerate(channels)}
    conv = journeys[journeys.converted]
    masks = conv.path.map(lambda p: sum({bit[c] for c in p}))
    vals = conv[weight] if weight else pd.Series(1.0, index=conv.index)

    # v[S] = sum over journeys whose channel set is a subset of S (zeta transform).
    v = np.zeros(1 << n)
    np.add.at(v, masks.to_numpy(), vals.to_numpy(dtype=float))
    for i in range(n):
        for S in range(1 << n):
            if S & (1 << i):
                v[S] += v[S ^ (1 << i)]

    size = np.array([bin(S).count("1") for S in range(1 << n)])
    w = np.array([factorial(k) * factorial(n - k - 1) / factorial(n) for k in range(n)])
    phi = {}
    for c, b in bit.items():
        S = np.array([S for S in range(1 << n) if not S & b])
        phi[c] = float((w[size[S]] * (v[S | b] - v[S])).sum())
    return pd.Series(phi)


# ---------------------------------------------------------------- report

def rule_based(journeys: pd.DataFrame) -> dict[str, pd.Series]:
    rows = []
    for path, conv, rev in zip(journeys.path, journeys.converted, journeys.revenue):
        if not conv:
            continue
        k = len(path)
        lin = 1 / k
        pos = [1.0] if k == 1 else [0.5, 0.5] if k == 2 else [0.4] + [0.2 / (k - 2)] * (k - 2) + [0.4]
        for i, c in enumerate(path):
            rows.append((c, float(i == 0), float(i == k - 1), lin, pos[i], rev))
    df = pd.DataFrame(rows, columns=["channel", "first_touch", "last_touch", "linear", "position_based", "rev"])
    return {m: df.groupby("channel")[m].sum() for m in ["first_touch", "last_touch", "linear", "position_based"]} | {
        f"{m}__rev": (df[m] * df.rev).groupby(df.channel).sum() for m in ["first_touch", "last_touch", "linear", "position_based"]}


def compare(journeys: pd.DataFrame) -> pd.DataFrame:
    rb = rule_based(journeys)
    models = {
        "first_touch": (rb["first_touch"], rb["first_touch__rev"]),
        "last_touch": (rb["last_touch"], rb["last_touch__rev"]),
        "linear": (rb["linear"], rb["linear__rev"]),
        "position_based": (rb["position_based"], rb["position_based__rev"]),
        "markov": (markov_attribution(journeys), markov_attribution(journeys, "revenue")),
        "shapley": (shapley_attribution(journeys), shapley_attribution(journeys, "revenue")),
    }
    out = []
    for name, (cust, rev) in models.items():
        df = pd.DataFrame({"customers": cust, "revenue": rev}).fillna(0)
        df["revenue_share"] = df.revenue / df.revenue.sum()
        df["model"] = name
        out.append(df.rename_axis("channel").reset_index())
    res = pd.concat(out, ignore_index=True)
    res[["customers", "revenue"]] = res[["customers", "revenue"]].round(2)
    res["revenue_share"] = res.revenue_share.round(4)
    return res[["model", "channel", "customers", "revenue", "revenue_share"]]


def summary_table(res: pd.DataFrame) -> pd.DataFrame:
    """Wide view: revenue share by channel for each model, plus the gap between
    data-driven credit and last touch."""
    wide = res.pivot(index="channel", columns="model", values="revenue_share")
    wide = wide[["last_touch", "first_touch", "linear", "position_based", "markov", "shapley"]]
    wide["markov_vs_last_touch"] = wide.markov - wide.last_touch
    return wide.sort_values("markov", ascending=False).round(4).reset_index()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    j = load_journeys(args.db)
    res = compare(j)
    res.to_csv(args.out / "11_attribution_models.csv", index=False)
    wide = summary_table(res)
    wide.to_csv(args.out / "11_attribution_comparison.csv", index=False)
    print(f"{len(j):,} journeys, {int(j.converted.sum()):,} converted\n")
    print(wide.to_string(index=False))


if __name__ == "__main__":
    main()
