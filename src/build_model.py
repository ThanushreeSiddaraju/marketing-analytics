"""Load raw CSVs into DuckDB, clean them, and build the star schema.

Also writes output/00_data_quality.csv: what was wrong in the raw data and how
many rows each cleaning rule touched.

Usage:  python src/build_model.py [--raw data/raw] [--db data/marketing.duckdb]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_SQL = sorted((ROOT / "sql" / "model").glob("*.sql"))

# (check, table, SQL returning one number, action taken in staging)
QUALITY_CHECKS = [
    ("Exact duplicate ad rows", "ad_daily",
     "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM raw_ad_daily)) FROM raw_ad_daily",
     "Dropped duplicates"),
    ("Negative spend", "ad_daily", "SELECT COUNT(*) FROM raw_ad_daily WHERE spend < 0",
     "Sign flipped to positive"),
    ("Clicks greater than impressions", "ad_daily", "SELECT COUNT(*) FROM raw_ad_daily WHERE clicks > impressions",
     "Clicks re-estimated from the creative's usual click rate"),
    ("Spend over $2 billed with zero impressions", "ad_daily",
     "SELECT COUNT(*) FROM raw_ad_daily WHERE impressions = 0 AND spend > 2",
     "Kept (reporting outage, spend is real)"),
    ("Non-standard channel names", "sessions",
     "SELECT COUNT(*) FROM raw_sessions s JOIN channel_map m ON s.channel = m.raw_name",
     "Mapped to standard names"),
    ("Missing device", "sessions", "SELECT COUNT(*) FROM raw_sessions WHERE device IS NULL",
     "Set to 'unknown'"),
    ("Duplicated lead IDs", "leads", "SELECT COUNT(*) - COUNT(DISTINCT lead_id) FROM raw_leads",
     "Kept first row per lead"),
]


def build(raw: Path, db: Path) -> pd.DataFrame:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    try:
        for f in MODEL_SQL:
            con.execute(f.read_text().replace("{raw}", raw.as_posix()))
        rows = [dict(check=c, table=t, rows_affected=con.execute(q).fetchone()[0], action=a)
                for c, t, q, a in QUALITY_CHECKS]
        dq = pd.DataFrame(rows)
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("fact_ad_daily", "fact_sessions", "fact_leads", "fact_orders", "fact_journeys")}
    finally:
        con.close()
    print("model built:", ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    return dq


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    args = ap.parse_args()
    dq = build(args.raw, args.db)
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    dq.to_csv(out / "00_data_quality.csv", index=False)
    print(dq.to_string(index=False))


if __name__ == "__main__":
    main()
