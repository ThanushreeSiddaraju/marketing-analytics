"""Build the DuckDB model, run every query in sql/analysis/ and the models, and write the results.

Outputs (output/):
  00_data_quality.csv         what the cleaning step fixed
  01_... .. 10_... .csv       one CSV per analysis query
  11_... .. 14_... .csv       attribution models, lead scoring, MMM and budget split
  16_anomaly_*.csv            days where a channel's numbers looked wrong
  15_hillstrom_*.csv          the real email experiment (downloaded on first run)
  marketing_report.xlsx       all of the above, one sheet each

Usage:
  python src/run_analysis.py                 # uses data/raw (run make_sample_data.py first)
  python src/run_analysis.py --raw my/exports --skip-build
  python src/run_analysis.py --skip-models   # SQL only
  python src/run_analysis.py --skip-real     # don't download or analyse the real dataset
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

import anomalies
import attribution
import hillstrom
import lead_scoring
import mmm
from build_model import build

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_SQL = sorted((ROOT / "sql" / "analysis").glob("*.sql"))


def run_queries(db: Path) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return {f.stem: con.execute(f.read_text()).df() for f in ANALYSIS_SQL}
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    ap.add_argument("--skip-build", action="store_true", help="reuse the existing DuckDB file")
    ap.add_argument("--skip-models", action="store_true", help="only run the SQL")
    ap.add_argument("--skip-real", action="store_true", help="skip the real Hillstrom email experiment")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    results: dict[str, pd.DataFrame] = {}
    if not args.skip_build:
        results["00_data_quality"] = build(args.raw, args.db)
    results.update(run_queries(args.db))
    if not args.skip_models:
        att = attribution.compare(attribution.load_journeys(args.db))
        results["11_attribution_models"] = att
        results["11_attribution_comparison"] = attribution.summary_table(att)
        results.update(lead_scoring.run(args.db))
        results.update(anomalies.run(args.db))
        m = mmm.run()
        m.pop("_weekly").to_csv(args.out / "13_mmm_weekly_data.csv", index=False)
        results.update(m)
    if not args.skip_real:
        try:
            results.update(hillstrom.run())
        except RuntimeError as e:
            print(f"  skipping the real dataset: {e}")

    with pd.ExcelWriter(args.out / "marketing_report.xlsx") as xl:
        for name, df in results.items():
            df.to_csv(args.out / f"{name}.csv", index=False)
            df.to_excel(xl, sheet_name=name[:31], index=False)
            print(f"  {name:<28} {len(df):>5} rows")

    k = results["10_kpi_summary"].iloc[0]
    print(f"\nspend ${k.total_spend:,.0f} | leads {int(k.leads):,} | customers {int(k.customers):,} | "
          f"paid ROAS {k.paid_roas:.2f} | paid CAC ${k.paid_cac:,.0f} -> {args.out}")


if __name__ == "__main__":
    main()
