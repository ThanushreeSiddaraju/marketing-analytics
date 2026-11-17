"""Lead scoring: predict which new leads become paying customers.

Only uses what's known when the form is submitted (channel, company size,
device, region, the ad's offer, pages viewed and earlier visits). Nothing from
the sales stages, so there's no leakage. I also tried industry, hour, weekday
and number of distinct channels; they made the validation scores slightly worse,
so they're out.

Validation is month by month: train on everything before July and score July,
train on everything before August and score August, and so on to October. The
deciles and calibration use those pooled out-of-sample scores. Leads from
November and December are left out because most haven't had time to close yet
(90% of wins happen within ~45 days).

Outputs (output/):
  12_lead_scoring_metrics.csv   AUC, PR-AUC, Brier score per test month, XGBoost vs logistic regression
  12_lead_score_deciles.csv     conversion rate and lift by score decile on the test set
  12_lead_score_calibration.csv predicted vs actual conversion in 10 bins
  12_lead_score_drivers.csv     mean |SHAP| per feature

Usage:  python src/lead_scoring.py [--db data/marketing.duckdb] [--out output]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]

CATEGORICAL = ["channel", "company_size", "device", "region", "offer_type"]
NUMERIC = ["landing_pageviews", "prior_visits"]
TEST_MONTHS = [7, 8, 9, 10]
TARGET = "is_customer"


def load_leads(db: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("""
            WITH j AS (
                SELECT lead_id,
                       max(touches) - 1 AS prior_visits,
                       count(DISTINCT channel) AS distinct_channels
                FROM fact_journeys GROUP BY lead_id
            )
            SELECT l.lead_id, l.created_at, l.channel, l.company_size, l.industry,
                   l.device, l.region, coalesce(cr.offer_type, 'none') AS offer_type,
                   l.landing_pageviews, j.prior_visits, j.distinct_channels,
                   hour(l.created_at) AS hour, isodow(l.created_at) AS weekday,
                   l.is_customer
            FROM fact_leads l
            JOIN j USING (lead_id)
            LEFT JOIN dim_creative cr USING (creative_id)
            WHERE l.created_at < DATE '2025-11-01'
            ORDER BY l.created_at
        """).df()
    finally:
        con.close()


def rolling_splits(df: pd.DataFrame):
    month = df.created_at.dt.month
    for m in TEST_MONTHS:
        yield m, df[month < m], df[month == m]


def to_xgb(df: pd.DataFrame) -> pd.DataFrame:
    X = df[CATEGORICAL + NUMERIC].copy()
    for c in CATEGORICAL:
        X[c] = X[c].astype("category")
    return X


def fit_xgb(train: pd.DataFrame, seed: int = 0) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(
        n_estimators=200, learning_rate=0.03, max_depth=2, min_child_weight=20,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=10.0,
        enable_categorical=True, tree_method="hist", eval_metric="logloss", random_state=seed,
    )
    model.fit(to_xgb(train), train[TARGET])
    return model


def fit_logit(train: pd.DataFrame):
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC),
    ])
    model = make_pipeline(pre, LogisticRegression(max_iter=2000, C=0.3))
    model.fit(train[CATEGORICAL + NUMERIC], train[TARGET])
    return model


def metrics(y: pd.Series, p: np.ndarray, name: str, month) -> dict:
    return dict(model=name, test_month=month, n_test=len(y), customers=int(y.sum()), base_rate=round(y.mean(), 4),
                roc_auc=round(roc_auc_score(y, p), 4), pr_auc=round(average_precision_score(y, p), 4),
                brier=round(brier_score_loss(y, p), 5))


def deciles(y: pd.Series, p: np.ndarray) -> pd.DataFrame:
    d = pd.DataFrame({"y": y.to_numpy(), "p": p})
    d["decile"] = 10 - pd.qcut(d.p.rank(method="first"), 10, labels=False)  # 1 = highest scores
    g = d.groupby("decile").agg(leads=("y", "size"), customers=("y", "sum"), avg_score=("p", "mean"))
    g["conversion_rate"] = g.customers / g.leads
    g["lift"] = g.conversion_rate / d.y.mean()
    g["cumulative_share_of_customers"] = g.customers.cumsum() / g.customers.sum()
    return g.round(4).reset_index()


def calibration(y: pd.Series, p: np.ndarray) -> pd.DataFrame:
    d = pd.DataFrame({"y": y.to_numpy(), "p": p})
    d["bin"] = pd.qcut(d.p.rank(method="first"), 10, labels=False) + 1
    return d.groupby("bin").agg(predicted=("p", "mean"), actual=("y", "mean"), leads=("y", "size")).round(4).reset_index()


def drivers(model: xgb.XGBClassifier, X: pd.DataFrame) -> pd.DataFrame:
    sv = shap.TreeExplainer(model).shap_values(X)
    imp = pd.DataFrame({"feature": X.columns, "mean_abs_shap": np.abs(sv).mean(axis=0)})
    imp["share"] = imp.mean_abs_shap / imp.mean_abs_shap.sum()
    return imp.sort_values("mean_abs_shap", ascending=False).round(4).reset_index(drop=True)


def run(db: Path) -> dict[str, pd.DataFrame]:
    df = load_leads(db)
    rows, scored = [], []
    for m, train, test in rolling_splits(df):
        xg, lr = fit_xgb(train), fit_logit(train)
        p_xgb = xg.predict_proba(to_xgb(test))[:, 1]
        p_lr = lr.predict_proba(test[CATEGORICAL + NUMERIC])[:, 1]
        y = test[TARGET].astype(int)
        rows += [metrics(y, p_xgb, "xgboost", m), metrics(y, p_lr, "logistic_regression", m)]
        scored.append(pd.DataFrame({"y": y.to_numpy(), "xgb": p_xgb, "lr": p_lr}))
    pooled = pd.concat(scored, ignore_index=True)
    for col, name in [("xgb", "xgboost"), ("lr", "logistic_regression")]:
        rows.append(metrics(pooled.y, pooled[col].to_numpy(), name, "all"))

    final = fit_xgb(df)
    return {
        "12_lead_scoring_metrics": pd.DataFrame(rows),
        "12_lead_score_deciles": deciles(pooled.y, pooled.xgb.to_numpy()),
        "12_lead_score_calibration": calibration(pooled.y, pooled.xgb.to_numpy()),
        "12_lead_score_drivers": drivers(final, to_xgb(df)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, df in run(args.db).items():
        df.to_csv(args.out / f"{name}.csv", index=False)
        print(f"\n{name}\n{df.to_string(index=False)}")


if __name__ == "__main__":
    main()
