"""Bundle the analysis outputs into site/data/site.json for the dashboard.

Run after run_analysis.py. The site itself is static (site/index.html,
site/app.js, site/style.css) and only reads this one file.

Usage:  python src/build_site.py [--out-dir output] [--site site]
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def records(df: pd.DataFrame, cols: list[str] | None = None) -> list[dict]:
    df = df[cols] if cols else df
    out = []
    for row in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()})
    return out


def build(out_dir: Path) -> dict:
    r = lambda name: pd.read_csv(out_dir / f"{name}.csv")  # noqa: E731

    ch = r("01_channel_performance")
    ltv = r("07_ltv_cac")[["channel", "ltv_to_cac", "payback_months", "monthly_churn"]]
    ch = ch.merge(ltv, on="channel", how="left")

    monthly = r("05_monthly_trends").groupby("year_month", as_index=False)[
        ["spend", "leads", "new_customers", "revenue"]].sum()

    creative = r("09_creative_performance")
    offers = (creative.groupby("offer_type")[["impressions", "clicks", "visits", "leads"]].sum()
              .assign(ctr=lambda d: d.clicks / d.impressions, visit_to_lead=lambda d: d.leads / d.visits)
              .sort_values("ctr", ascending=False).reset_index())

    seg = r("06_segment_performance")
    device = (seg.groupby("device")[["spend", "visits", "leads", "customers", "revenue"]].sum()
              .assign(visit_to_lead=lambda d: d.leads / d.visits, cac=lambda d: d.spend / d.customers,
                      roas=lambda d: d.revenue / d.spend).reset_index())

    att = r("11_attribution_comparison")
    lead_metrics = r("12_lead_scoring_metrics")
    pooled = lead_metrics[lead_metrics.test_month.astype(str) == "all"]

    real = None
    if (out_dir / "15_hillstrom_effects.csv").exists():
        seg = r("15_hillstrom_segments")
        real = {
            "balance": records(r("15_hillstrom_balance")),
            "effects": records(r("15_hillstrom_effects")),
            "cuped": records(r("15_hillstrom_cuped")),
            "segments": records(seg[seg.dimension == "previous purchases"]),
            "targeting": records(r("15_hillstrom_targeting")),
            "power": records(r("15_hillstrom_power")),
        }

    return {
        "built": date.today().isoformat(),
        "real": real,
        "kpi": records(r("10_kpi_summary"))[0],
        "channels": records(ch, ["channel", "channel_type", "spend", "leads", "customers", "revenue", "ctr",
                                 "cost_per_lead", "cac", "roas", "ltv_to_cac", "payback_months", "monthly_churn"]),
        "funnel": records(r("03_marketing_funnel"), ["stage", "volume", "step_conversion"]),
        "monthly": records(monthly),
        "offers": records(offers, ["offer_type", "ctr", "visit_to_lead"]),
        "devices": records(device, ["device", "spend", "visit_to_lead", "cac", "roas"]),
        "quality": records(r("00_data_quality")),
        "attribution": records(att, ["channel", "last_touch", "first_touch", "linear", "markov", "shapley"]),
        "lead_scoring": {
            "pooled": records(pooled, ["model", "n_test", "customers", "base_rate", "roc_auc", "pr_auc"]),
            "deciles": records(r("12_lead_score_deciles"), ["decile", "leads", "customers", "conversion_rate", "lift",
                                                           "cumulative_share_of_customers"]),
            "drivers": records(r("12_lead_score_drivers"), ["feature", "share"]),
        },
        "mmm": {
            "fit": records(r("13_mmm_fit"))[0],
            "recovery": records(r("13_mmm_parameter_recovery")),
            "channels": records(r("13_mmm_channels")),
            "curves": records(r("13_mmm_response_curves")),
            "budget": records(r("14_budget_allocation")),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "output")
    ap.add_argument("--site", type=Path, default=ROOT / "site")
    args = ap.parse_args()
    data = build(args.out_dir)
    dest = args.site / "data" / "site.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote {dest} ({dest.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
