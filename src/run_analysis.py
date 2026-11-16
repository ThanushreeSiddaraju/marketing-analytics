"""Build the DuckDB model, run every query in sql/analysis/, and write the results.

Outputs (output/):
  00_data_quality.csv         what the cleaning step fixed
  01_... .. 10_... .csv       one CSV per analysis query
  marketing_report.xlsx       all of the above, one sheet each

Usage:
  python src/run_analysis.py                 # uses data/raw (run make_sample_data.py first)
  python src/run_analysis.py --raw my/exports --skip-build
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

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
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    results: dict[str, pd.DataFrame] = {}
    if not args.skip_build:
        results["00_data_quality"] = build(args.raw, args.db)
    results.update(run_queries(args.db))

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
