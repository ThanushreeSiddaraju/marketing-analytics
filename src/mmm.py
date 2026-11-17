"""Marketing mix model and budget reallocation.

One year of data isn't enough to fit an MMM honestly, so this simulates three
years of weekly spend and trial sign-ups for Lumora's five paid ad channels,
with effects I choose up front. That way I can check whether the model gets the
true effects back before trusting anything it says about spend.

The model, per channel:
  carryover    a_t = spend_t + decay * a_{t-1}           (geometric adstock)
  saturation   effect = beta * a / (a + half_sat)         (Hill curve, shape 1)
plus a baseline, a linear trend and yearly seasonality. It's fitted with
non-linear least squares from several starting points, with weak priors on
carryover and saturation (so it's a MAP estimate, like a Bayesian MMM would
give with the same priors). Uncertainty comes from a
moving-block bootstrap of the residuals (200 refits). The last 13 weeks are held
out to check the forecast.

The budget step keeps total weekly spend fixed and moves money between
channels (each channel stays within 50% of its current level) to maximise
sign-ups predicted by the fitted curves. The result is then scored against the
true curves too, so you can see how much of the promised gain is real.

Outputs (output/):
  13_mmm_fit.csv                 R², holdout MAPE
  13_mmm_parameter_recovery.csv  true vs estimated parameters with 90% intervals
  13_mmm_channels.csv            contribution, cost per sign-up and marginal cost per channel
  13_mmm_response_curves.csv     estimated and true weekly response by spend level
  14_budget_allocation.csv       current vs recommended weekly spend

Usage:  python src/mmm.py [--out output] [--seed 7] [--boot 200]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, minimize

ROOT = Path(__file__).resolve().parents[1]
WEEKS = 156
HOLDOUT = 13

# Average weekly spend is roughly Lumora's 2025 level. True effects:
# decay = carryover, half_sat = adstocked weekly spend where the channel gets
# half its maximum effect, beta = maximum extra sign-ups per week.
TRUTH = pd.DataFrame([
    ("Google Search",  1950, 0.20, 2600, 210.0),
    ("Meta Ads",       1375, 0.45, 2200,  70.0),
    ("LinkedIn Ads",   1090, 0.55, 3800,  95.0),
    ("Google Display",  630, 0.35,  500,  16.0),
    ("TikTok Ads",      400, 0.30,  450,   9.0),
], columns=["channel", "mean_spend", "decay", "half_sat", "beta"]).set_index("channel")
BASELINE, TREND, SEASON_AMP, NOISE_SD = 120.0, 0.12, 0.10, 9.0


def adstock(x: np.ndarray, decay: float) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    carry = 0.0
    for t, v in enumerate(x):
        carry = v + decay * carry
        out[t] = carry
    return out


def hill(a: np.ndarray, half_sat: float, beta: float) -> np.ndarray:
    return beta * a / (a + half_sat)


def simulate(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(WEEKS)
    df = pd.DataFrame({"week": pd.date_range("2023-01-02", periods=WEEKS, freq="W-MON")})
    signups = BASELINE + TREND * t + BASELINE * SEASON_AMP * np.sin(2 * np.pi * t / 52)
    for i, (ch, r) in enumerate(TRUTH.iterrows()):
        season = 1 + 0.25 * np.sin(2 * np.pi * t / 52 + i)
        spend = r.mean_spend * season * rng.lognormal(-0.08, 0.4, WEEKS)
        if ch in ("TikTok Ads", "Google Display"):
            spend *= rng.random(WEEKS) > 0.15          # dark weeks
        if ch == "Meta Ads":
            spend[rng.choice(WEEKS, 10, replace=False)] *= 2.5   # launch bursts
        df[ch] = spend.round(2)
        signups = signups + hill(adstock(spend, r.decay), r.half_sat, r.beta)
    df["signups"] = np.round(signups + rng.normal(0, NOISE_SD, WEEKS)).clip(min=0)
    return df


# ---------------------------------------------------------------- model

CH = list(TRUTH.index)
K = len(CH)


def unpack(theta: np.ndarray):
    decay, log_hs, beta = theta[:K], theta[K:2 * K], theta[2 * K:3 * K]
    base, trend, s1, c1 = theta[3 * K:]
    return decay, np.exp(log_hs), beta, base, trend, s1, c1


def predict(theta: np.ndarray, spend: np.ndarray, t: np.ndarray) -> np.ndarray:
    decay, hs, beta, base, trend, s1, c1 = unpack(theta)
    y = base + trend * t + s1 * np.sin(2 * np.pi * t / 52) + c1 * np.cos(2 * np.pi * t / 52)
    for j in range(K):
        y = y + hill(adstock(spend[:, j], decay[j]), hs[j], beta[j])
    return y


# Weak priors, the same idea as a Bayesian MMM: carryover is usually modest,
# and channels are usually run somewhere near their half-saturation point.
PRIOR_DECAY, PRIOR_DECAY_SD = 0.3, 0.2
PRIOR_LOG_HS_SD = 0.7


def fit(spend: np.ndarray, y: np.ndarray, t: np.ndarray, rng: np.random.Generator, starts: int = 8,
        x0: np.ndarray | None = None, sigma: float | None = None) -> np.ndarray:
    """MAP fit: squared errors scaled by the noise level plus the prior penalties.
    `sigma` is the residual noise; if not given it's estimated from an
    unpenalised first pass."""
    mean = spend.mean(axis=0)
    hs_centre = np.log(mean / (1 - PRIOR_DECAY))
    if sigma is None:
        sigma = float(np.std(y - predict(_fit(spend, y, t, rng, starts, x0, None), spend, t)))

    def resid(p):
        r = (predict(p, spend, t) - y) / sigma
        return np.r_[r, (p[:K] - PRIOR_DECAY) / PRIOR_DECAY_SD, (p[K:2 * K] - hs_centre) / PRIOR_LOG_HS_SD]

    return _fit(spend, y, t, rng, starts, x0, resid)


def _fit(spend, y, t, rng, starts, x0, resid) -> np.ndarray:
    mean = spend.mean(axis=0)
    if resid is None:
        resid = lambda p: predict(p, spend, t) - y  # noqa: E731
    lo = np.r_[np.zeros(K), np.log(mean * 0.1), np.zeros(K), -np.inf, -np.inf, -np.inf, -np.inf]
    hi = np.r_[np.full(K, 0.9), np.log(mean * 20), np.full(K, 500.0), np.inf, np.inf, np.inf, np.inf]
    best, best_cost = None, np.inf
    inits = [x0] if x0 is not None else []
    for _ in range(starts - len(inits)):
        inits.append(np.r_[rng.uniform(0.05, 0.7, K), np.log(mean * rng.uniform(0.5, 4, K)),
                           rng.uniform(5, 150, K), y.mean() * 0.5, 0.0, 0.0, 0.0])
    for th in inits:
        r = least_squares(resid, np.clip(th, lo + 1e-9, hi - 1e-9),
                          bounds=(lo, hi), method="trf", max_nfev=4000)
        if r.cost < best_cost:
            best, best_cost = r.x, r.cost
    return best


def block_bootstrap(theta, spend, y, t, n_boot, rng, block=8) -> np.ndarray:
    fitted = predict(theta, spend, t)
    resid = y - fitted
    sigma = float(resid.std())
    n = len(y)
    draws = []
    for _ in range(n_boot):
        idx = np.concatenate([np.arange(s, s + block) % n for s in rng.integers(0, n, n // block + 1)])[:n]
        draws.append(fit(spend, fitted + resid[idx], t, rng, starts=1, x0=theta, sigma=sigma))
    return np.array(draws)


# ---------------------------------------------------------------- budget

def weekly_response(spend: np.ndarray, decay, hs, beta) -> np.ndarray:
    """Sign-ups per week if this spend were held steady (steady-state adstock)."""
    return hill(spend / (1 - decay), hs, beta)


def optimise(current: np.ndarray, decay, hs, beta, band: float = 0.5) -> np.ndarray:
    total = current.sum()
    res = minimize(lambda x: -weekly_response(x, decay, hs, beta).sum(), current,
                   method="SLSQP", bounds=[(c * (1 - band), c * (1 + band)) for c in current],
                   constraints=[{"type": "eq", "fun": lambda x: x.sum() - total}])
    return res.x


# ---------------------------------------------------------------- run

def run(seed: int = 7, n_boot: int = 200) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed + 1)
    df = simulate(seed)
    spend, y, t = df[CH].to_numpy(), df.signups.to_numpy(float), np.arange(WEEKS, dtype=float)
    tr = slice(0, WEEKS - HOLDOUT)

    # holdout check, then refit on everything for the rest
    th_tr = fit(spend[tr], y[tr], t[tr], rng)
    pred_all = predict(th_tr, spend, t)
    ho = slice(WEEKS - HOLDOUT, WEEKS)
    theta = fit(spend, y, t, rng)
    fitted = predict(theta, spend, t)
    fit_df = pd.DataFrame([dict(
        weeks=WEEKS, holdout_weeks=HOLDOUT,
        r2_in_sample=round(1 - ((y - fitted) ** 2).sum() / ((y - y.mean()) ** 2).sum(), 4),
        holdout_mape=round(np.mean(np.abs(pred_all[ho] - y[ho]) / y[ho]), 4),
        residual_sd=round(float(np.std(y - fitted)), 2), true_noise_sd=NOISE_SD,
    )])

    boot = block_bootstrap(theta, spend, y, t, n_boot, rng)
    decay, hs, beta, *_ = unpack(theta)
    b_decay, b_hs, b_beta = boot[:, :K], np.exp(boot[:, K:2 * K]), boot[:, 2 * K:3 * K]

    rec = []
    for j, ch in enumerate(CH):
        for name, est, draws in [("decay", decay, b_decay), ("half_sat", hs, b_hs), ("beta", beta, b_beta)]:
            lo, hi = np.percentile(draws[:, j], [5, 95])
            true = TRUTH.loc[ch, name]
            rec.append(dict(channel=ch, parameter=name, true=true, estimate=round(est[j], 3),
                            ci90_low=round(lo, 3), ci90_high=round(hi, 3), inside_interval=bool(lo <= true <= hi)))
    rec = pd.DataFrame(rec)

    # channel economics at the current average spend
    cur = spend.mean(axis=0)
    tv = TRUTH[["decay", "half_sat", "beta"]].to_numpy().T
    contrib = np.array([hill(adstock(spend[:, j], decay[j]), hs[j], beta[j]).sum() for j in range(K)])
    true_contrib = np.array([hill(adstock(spend[:, j], tv[0][j]), tv[1][j], tv[2][j]).sum() for j in range(K)])

    def marginal(x, d, h, b, eps=1.0):
        # cost of one more weekly sign-up at spend x; capped at $10k because a
        # bootstrap draw with ~zero effect would otherwise give infinity
        gain = weekly_response(x + eps, d, h, b) - weekly_response(x, d, h, b)
        return np.minimum(eps / np.maximum(gain, 1e-12), 10_000)

    boot_mc = np.array([marginal(cur, b_decay[i], b_hs[i], b_beta[i]) for i in range(n_boot)])
    ch_df = pd.DataFrame({
        "channel": CH, "total_spend": spend.sum(axis=0).round(0),
        "signups_from_channel": contrib.round(0), "true_signups_from_channel": true_contrib.round(0),
        "cost_per_signup": (spend.sum(axis=0) / contrib).round(2),
        "true_cost_per_signup": (spend.sum(axis=0) / true_contrib).round(2),
        "marginal_cost_per_signup": marginal(cur, decay, hs, beta).round(2),
        "marginal_ci90_low": np.percentile(boot_mc, 5, axis=0).round(2),
        "marginal_ci90_high": np.percentile(boot_mc, 95, axis=0).round(2),
        "true_marginal_cost_per_signup": marginal(cur, *tv).round(2),
    })

    curves = []
    for j, ch in enumerate(CH):
        for x in np.linspace(0, cur[j] * 3, 31):
            curves.append(dict(channel=ch, weekly_spend=round(x, 2),
                               signups=round(float(weekly_response(x, decay[j], hs[j], beta[j])), 2),
                               true_signups=round(float(weekly_response(x, *tv[:, j])), 2)))
    curves = pd.DataFrame(curves)

    new = optimise(cur, decay, hs, beta)
    budget = pd.DataFrame({
        "channel": CH, "current_weekly_spend": cur.round(0), "recommended_weekly_spend": new.round(0),
        "change_pct": ((new / cur - 1) * 100).round(1),
        "signups_now_model": weekly_response(cur, decay, hs, beta).round(1),
        "signups_after_model": weekly_response(new, decay, hs, beta).round(1),
        "signups_now_true": weekly_response(cur, *tv).round(1),
        "signups_after_true": weekly_response(new, *tv).round(1),
    })
    tot = budget.drop(columns="channel").sum()
    tot["change_pct"] = np.nan
    budget = pd.concat([budget, pd.DataFrame([{"channel": "Total", **tot.round(1).to_dict()}])], ignore_index=True)

    return {"13_mmm_fit": fit_df, "13_mmm_parameter_recovery": rec, "13_mmm_channels": ch_df,
            "13_mmm_response_curves": curves, "14_budget_allocation": budget, "_weekly": df}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--boot", type=int, default=200)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.seed, args.boot)
    res.pop("_weekly").to_csv(args.out / "13_mmm_weekly_data.csv", index=False)
    for name, df in res.items():
        df.to_csv(args.out / f"{name}.csv", index=False)
        if name != "13_mmm_response_curves":
            print(f"\n{name}\n{df.to_string(index=False)}")


if __name__ == "__main__":
    main()
