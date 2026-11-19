"""Real data: Kevin Hillstrom's email marketing experiment (MineThatData, 2008).

64,000 customers of an online retailer were randomly sent a men's email, a
women's email, or nothing, and their site visits, purchases and spend were
tracked for two weeks. Because the split was random, the difference between
each email group and the no-email group is the effect of the email.

What this does:
  - downloads the CSV once into data/real/ and checks it against a known checksum
  - loads and cleans it with sql/real/01_hillstrom.sql
  - checks the randomisation worked (group sizes and pre-send balance)
  - measures each email's lift on visits, purchases and spend, with 95%
    intervals and a Holm correction for testing several things at once
  - uses last year's spend as a CUPED covariate to tighten the spend estimate
  - looks at who each email works for, and what targeting would be worth
  - works out how big a test would need to be to measure the purchase lift

Outputs (output/):
  15_hillstrom_balance.csv     group sizes, sample ratio test, pre-send balance
  15_hillstrom_effects.csv     lift per email and metric
  15_hillstrom_cuped.csv       spend lift with and without CUPED
  15_hillstrom_segments.csv    lift by customer group
  15_hillstrom_targeting.csv   incremental revenue per 1,000 customers for each policy
  15_hillstrom_power.csv       detectable effects and required sample sizes

Usage:  python src/hillstrom.py [--out output]
"""
from __future__ import annotations

import argparse
import hashlib
import time
import urllib.request
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
URL = "http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
SHA256 = "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece"
CSV = ROOT / "data" / "real" / "hillstrom.csv"
ARMS = ["mens_email", "womens_email"]
METRICS = {"visited": "visit rate", "converted": "purchase rate", "spend": "spend per customer"}


def fetch(path: Path = CSV, attempts: int = 3) -> Path:
    """Download the CSV if it isn't already here, and check it's the right file."""
    def ok(p):
        return p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == SHA256

    if ok(path):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    for i in range(attempts):
        try:
            with urllib.request.urlopen(URL, timeout=60) as r:
                tmp.write_bytes(r.read())
            if ok(tmp):
                tmp.replace(path)
                return path
            raise ValueError("checksum didn't match")
        except Exception as e:  # noqa: BLE001 - retry anything, report the last one
            err = e
            time.sleep(2 * (i + 1))
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"couldn't download the Hillstrom data: {err}")


def load(csv: Path) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute((ROOT / "sql" / "real" / "01_hillstrom.sql").read_text().replace("{csv}", str(csv)))
        return con.execute("SELECT * FROM hillstrom").df()
    finally:
        con.close()


# ---------------------------------------------------------------- stats helpers

def diff_ci(t: np.ndarray, c: np.ndarray, alpha: float = 0.05) -> dict:
    """Difference in means with a Welch (unequal variance) interval and p-value."""
    mt, mc = t.mean(), c.mean()
    vt, vc = t.var(ddof=1) / len(t), c.var(ddof=1) / len(c)
    se = np.sqrt(vt + vc)
    df = (vt + vc) ** 2 / (vt ** 2 / (len(t) - 1) + vc ** 2 / (len(c) - 1))
    q = stats.t.ppf(1 - alpha / 2, df)
    d = mt - mc
    p = 2 * stats.t.sf(abs(d) / se, df)
    return dict(control=mc, treated=mt, lift=d, ci_low=d - q * se, ci_high=d + q * se,
                relative_lift=d / mc if mc else np.nan, se=se, p_value=p)


def holm(p: pd.Series) -> pd.Series:
    """Holm-Bonferroni adjusted p-values."""
    order = p.sort_values().index
    m = len(p)
    adj, running = pd.Series(index=p.index, dtype=float), 0.0
    for k, i in enumerate(order):
        running = max(running, min(1.0, (m - k) * p[i]))
        adj[i] = running
    return adj


def cuped(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Remove the part of y explained by a pre-experiment covariate x."""
    theta = np.cov(y, x, ddof=1)[0, 1] / x.var(ddof=1)
    return y - theta * (x - x.mean())


# ---------------------------------------------------------------- analysis

def balance(df: pd.DataFrame) -> pd.DataFrame:
    counts = df.arm.value_counts().reindex(["control", *ARMS])
    chi2, p = stats.chisquare(counts.to_numpy())
    rows = [dict(check="customers", group=a, value=int(n), note="") for a, n in counts.items()]
    rows.append(dict(check="sample ratio test (equal thirds)", group="all", value=round(p, 4),
                     note=f"chi-square {chi2:.2f}; a p-value under 0.001 would mean the split is broken"))
    covs = {"months_since_purchase": "months since last purchase", "spend_last_year": "spend last year",
            "new_customer": "new customer share", "bought_mens": "bought men's", "bought_womens": "bought women's"}
    ctrl = df[df.arm == "control"]
    for col, label in covs.items():
        for a in ARMS:
            t = df.loc[df.arm == a, col].astype(float)
            c = ctrl[col].astype(float)
            smd = (t.mean() - c.mean()) / np.sqrt((t.var() + c.var()) / 2)
            rows.append(dict(check=f"balance: {label}", group=a, value=round(smd, 4),
                             note="standardised difference vs control; under 0.1 is balanced"))
    return pd.DataFrame(rows)


def effects(df: pd.DataFrame) -> pd.DataFrame:
    ctrl = df[df.arm == "control"]
    rows = []
    for a in ARMS:
        t = df[df.arm == a]
        for m, label in METRICS.items():
            r = diff_ci(t[m].astype(float).to_numpy(), ctrl[m].astype(float).to_numpy())
            rows.append(dict(arm=a, metric=m, label=label, n_treated=len(t), n_control=len(ctrl), **r))
    out = pd.DataFrame(rows)
    out["p_holm"] = holm(out.p_value)
    out["significant"] = out.p_holm < 0.05
    return out.drop(columns="se")


def cuped_table(df: pd.DataFrame) -> pd.DataFrame:
    ctrl = df[df.arm == "control"]
    rows = []
    corr = np.corrcoef(df.spend, df.spend_last_year)[0, 1]
    for a in ARMS:
        sub = pd.concat([df[df.arm == a], ctrl])
        adj = cuped(sub.spend.to_numpy(), sub.spend_last_year.to_numpy())
        is_t = (sub.arm == a).to_numpy()
        raw = diff_ci(sub.spend.to_numpy()[is_t], sub.spend.to_numpy()[~is_t])
        cup = diff_ci(adj[is_t], adj[~is_t])
        rows.append(dict(arm=a, lift_raw=raw["lift"], ci_width_raw=raw["ci_high"] - raw["ci_low"],
                         lift_cuped=cup["lift"], ci_width_cuped=cup["ci_high"] - cup["ci_low"],
                         variance_reduction=1 - (cup["se"] / raw["se"]) ** 2, corr_with_covariate=corr))
    return pd.DataFrame(rows)


SEGMENTS = {"bought": "previous purchases", "new_customer": "new customer", "purchase_channel": "bought via",
            "area": "area", "history_segment": "spend last year"}


def segments(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col, label in SEGMENTS.items():
        for val, g in df.groupby(col):
            ctrl = g[g.arm == "control"]
            for a in ARMS:
                t = g[g.arm == a]
                v = diff_ci(t.visited.astype(float).to_numpy(), ctrl.visited.astype(float).to_numpy())
                s = diff_ci(t.spend.to_numpy(), ctrl.spend.to_numpy())
                rows.append(dict(dimension=label, segment=str(val).lower() if not isinstance(val, (bool, np.bool_)) else ("yes" if val else "no"),
                                 arm=a, customers=len(t) + len(ctrl), visit_lift=v["lift"],
                                 visit_ci_low=v["ci_low"], visit_ci_high=v["ci_high"],
                                 spend_lift=s["lift"], spend_ci_low=s["ci_low"], spend_ci_high=s["ci_high"]))
    return pd.DataFrame(rows)


def targeting(df: pd.DataFrame) -> pd.DataFrame:
    """Incremental spend per 1,000 customers for a few simple sending rules.

    Effects per group are estimated on half the customers and the policies are
    scored on the other half, so a rule doesn't get credit for fitting noise.
    """
    rng = np.random.default_rng(0)
    half = rng.random(len(df)) < 0.5
    fit, score = df[half], df[~half]

    def lift(d, a, mask=None):
        d = d if mask is None else d[mask(d)]
        return d.loc[d.arm == a, "spend"].mean() - d.loc[d.arm == "control", "spend"].mean()

    best = {}
    for b in ["mens only", "womens only", "both"]:
        m = lambda d, b=b: d.bought == b  # noqa: E731
        l_m, l_w = lift(fit, "mens_email", m), lift(fit, "womens_email", m)
        best[b] = "mens_email" if l_m >= l_w else "womens_email"

    def score_policy(choose):
        total, n = 0.0, len(score)
        for b, g in score.groupby("bought"):
            a = choose(b)
            if a is None:
                continue
            total += lift(g, a) * len(g)
        return total / n * 1000

    policies = {
        "email nobody": lambda b: None,
        "men's email to everyone": lambda b: "mens_email",
        "women's email to everyone": lambda b: "womens_email",
        "pick the email by what they bought before": lambda b: best[b],
    }
    rows = []
    for name, choose in policies.items():
        rows.append(dict(policy=name, incremental_spend_per_1000=score_policy(choose),
                         emails_per_1000=0 if name == "email nobody" else 1000))
    out = pd.DataFrame(rows)
    out["rule"] = [None, None, None, "; ".join(f"{k}: {v.replace('_', ' ')}" for k, v in best.items())]
    return out


def power(df: pd.DataFrame, alpha: float = 0.05, target_power: float = 0.8) -> pd.DataFrame:
    ctrl = df[df.arm == "control"]
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(target_power)
    n = int(df.arm.value_counts().min())
    rows = []
    for m, label in METRICS.items():
        y = ctrl[m].astype(float)
        sd = y.std()
        mde = (za + zb) * sd * np.sqrt(2 / n)
        rows.append(dict(metric=label, control_mean=y.mean(), customers_per_group=n,
                         min_detectable_lift=mde, min_detectable_relative=mde / y.mean()))
    for a in ARMS:
        t = df[df.arm == a]
        for m in ["converted", "spend"]:
            d = t[m].astype(float).mean() - ctrl[m].astype(float).mean()
            sd = np.sqrt((t[m].astype(float).var() + ctrl[m].astype(float).var()) / 2)
            need = int(np.ceil(2 * ((za + zb) * sd / d) ** 2))
            rows.append(dict(metric=f"{METRICS[m]} ({a.replace('_', ' ')} effect)", control_mean=ctrl[m].astype(float).mean(),
                             customers_per_group=need, min_detectable_lift=d, min_detectable_relative=d / ctrl[m].astype(float).mean()))
    return pd.DataFrame(rows)


def run(csv: Path | None = None) -> dict[str, pd.DataFrame]:
    df = load(csv or fetch())
    res = {
        "15_hillstrom_balance": balance(df),
        "15_hillstrom_effects": effects(df),
        "15_hillstrom_cuped": cuped_table(df),
        "15_hillstrom_segments": segments(df),
        "15_hillstrom_targeting": targeting(df),
        "15_hillstrom_power": power(df),
    }
    return {k: v.round(6) for k, v in res.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, df in run().items():
        df.to_csv(args.out / f"{name}.csv", index=False)
        print(f"\n{name}\n{df.to_string(index=False, max_colwidth=60)}")


if __name__ == "__main__":
    main()
