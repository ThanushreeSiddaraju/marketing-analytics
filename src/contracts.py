"""Check raw files against a data contract before anything is loaded.

Cleaning (sql/model/01_staging.sql) fixes the kinds of mess you expect in
real exports: duplicates, negative spend, inconsistent channel names. The
contract is for the other kind of problem, where a file isn't what the
pipeline was built for at all: a column renamed or missing, dates that won't
parse, an id column that's empty, rows from the wrong year. Those should stop
the build with a clear message instead of quietly producing wrong numbers.

Each file lists its columns with a type, whether blanks are allowed, and for
date columns the range they must fall in. Every value is read as text first
and then cast, so a value that won't parse is counted rather than crashing
the load.

Usage:  python src/contracts.py [--raw data/raw]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
YEAR = ("2025-01-01", "2025-12-31")


@dataclass(frozen=True)
class Col:
    type: str                      # DuckDB type to cast to
    required: bool = False         # no blanks allowed
    range: tuple[str, str] | None = None


CONTRACTS: dict[str, dict[str, Col]] = {
    "campaigns.csv": {
        "campaign_id": Col("VARCHAR", required=True), "campaign_name": Col("VARCHAR", required=True),
        "channel": Col("VARCHAR", required=True), "objective": Col("VARCHAR"),
        "start_date": Col("DATE", required=True, range=YEAR), "end_date": Col("DATE", required=True, range=YEAR),
        "daily_budget": Col("DOUBLE"),
    },
    "creatives.csv": {
        "creative_id": Col("VARCHAR", required=True), "campaign_id": Col("VARCHAR", required=True),
        "offer_type": Col("VARCHAR"), "tone": Col("VARCHAR"), "format": Col("VARCHAR"),
        "headline": Col("VARCHAR"), "cta": Col("VARCHAR"),
    },
    "ad_daily.csv": {
        "date": Col("DATE", required=True, range=YEAR), "campaign_id": Col("VARCHAR", required=True),
        "creative_id": Col("VARCHAR", required=True), "device": Col("VARCHAR"), "region": Col("VARCHAR"),
        "impressions": Col("BIGINT", required=True), "clicks": Col("BIGINT", required=True),
        "spend": Col("DOUBLE", required=True),
    },
    "sessions.csv": {
        "session_id": Col("VARCHAR", required=True), "user_id": Col("VARCHAR", required=True),
        "ts": Col("TIMESTAMP", required=True, range=YEAR), "channel": Col("VARCHAR", required=True),
        "campaign_id": Col("VARCHAR"), "creative_id": Col("VARCHAR"), "device": Col("VARCHAR"),
        "region": Col("VARCHAR"), "pageviews": Col("INTEGER"), "duration_sec": Col("INTEGER"),
        "bounced": Col("BOOLEAN"),
    },
    "leads.csv": {
        "lead_id": Col("VARCHAR", required=True), "user_id": Col("VARCHAR", required=True),
        "created_at": Col("TIMESTAMP", required=True, range=YEAR), "channel": Col("VARCHAR", required=True),
        "campaign_id": Col("VARCHAR"), "session_id": Col("VARCHAR", required=True),
        "company_size": Col("VARCHAR"), "industry": Col("VARCHAR"),
        "mql_at": Col("TIMESTAMP"), "sql_at": Col("TIMESTAMP"), "won_at": Col("TIMESTAMP"),
        "plan": Col("VARCHAR"), "mrr": Col("DOUBLE"),
    },
    "orders.csv": {
        "order_id": Col("VARCHAR", required=True), "user_id": Col("VARCHAR", required=True),
        "order_date": Col("DATE", required=True, range=YEAR), "revenue": Col("DOUBLE", required=True),
        "plan": Col("VARCHAR"), "is_first_order": Col("BOOLEAN"),
    },
}


class ContractError(ValueError):
    """Raised with every problem found, one per line."""


def check_file(con: duckdb.DuckDBPyConnection, path: Path, cols: dict[str, Col]) -> list[str]:
    name = path.name
    if not path.exists():
        return [f"{name}: file is missing"]
    src = f"read_csv('{path.as_posix()}', all_varchar = true, header = true)"
    header = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
    missing = [c for c in cols if c not in header]
    problems = [f"{name}: missing column {c!r}" for c in missing]
    present = [c for c in cols if c in header]
    if not present:
        return problems
    exprs = []
    for c in present:
        spec = cols[c]
        q = f'"{c}"'
        exprs.append(f"COUNT({q}) - COUNT(TRY_CAST({q} AS {spec.type}))")          # unparseable
        exprs.append(f"COUNT(*) - COUNT({q})" if spec.required else "0")              # blanks
        if spec.range:
            lo, hi = spec.range
            exprs.append(f"COUNT(*) FILTER (WHERE TRY_CAST({q} AS DATE) NOT BETWEEN DATE '{lo}' AND DATE '{hi}')")
        else:
            exprs.append("0")
    vals = con.execute(f"SELECT COUNT(*), {', '.join(exprs)} FROM {src}").fetchone()
    if vals[0] == 0:
        problems.append(f"{name}: no rows")
    for i, c in enumerate(present):
        bad_type, blanks, out_of_range = vals[1 + 3 * i: 4 + 3 * i]
        spec = cols[c]
        if bad_type:
            problems.append(f"{name}.{c}: {bad_type:,} value(s) aren't a valid {spec.type.lower()}")
        if blanks:
            problems.append(f"{name}.{c}: {blanks:,} blank value(s) in a required column")
        if out_of_range:
            problems.append(f"{name}.{c}: {out_of_range:,} date(s) outside {spec.range[0]} to {spec.range[1]}")
    return problems


def validate(raw: Path) -> None:
    """Raise ContractError listing every problem across all raw files, or return quietly."""
    con = duckdb.connect()
    try:
        problems = [p for f, cols in CONTRACTS.items() for p in check_file(con, raw / f, cols)]
    finally:
        con.close()
    if problems:
        raise ContractError("raw data doesn't match the contract:\n  " + "\n  ".join(problems))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args()
    validate(args.raw)
    print(f"all {len(CONTRACTS)} raw files match the contract")


if __name__ == "__main__":
    main()
