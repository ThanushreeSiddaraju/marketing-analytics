"""Score the analyst agent against the golden questions. Needs ANTHROPIC_API_KEY.

Each line of golden.jsonl has a question and a SQL query that gives the right
answer. The expected value is computed from the current database, so the set
still works if the sample data changes.

A question counts as correct when one of the agent's checked claims matches
the expected value. I also track "verified but wrong": answers that passed the
checks and the reviewer but still had the wrong number. That's the failure
that would actually reach someone, so it should stay at zero.

  python evals/run_evals.py                  # all questions
  python evals/run_evals.py --limit 5        # first five
  python evals/run_evals.py --ids linkedin_cac search_roas

Writes evals/results/latest.csv and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents.analyst import ask  # noqa: E402
from agents.llm import AgentFailed, make_client  # noqa: E402
from agents.sql_tool import SafeSQL  # noqa: E402
from agents.verify import close_enough  # noqa: E402


def load_golden(db: Path, path: Path = ROOT / "evals" / "golden.jsonl") -> list[dict]:
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    con = duckdb.connect(str(db), read_only=True)
    try:
        for it in items:
            it["expected"] = float(con.execute(it["sql"]).fetchone()[0])
    finally:
        con.close()
    return items


def grade(answer, expected: float) -> bool:
    return any(c.ok and close_enough(float(c.claim["value"]), expected) for c in answer.checks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    items = load_golden(args.db)
    if args.ids:
        items = [i for i in items if i["id"] in args.ids]
    if args.limit:
        items = items[: args.limit]
    client = make_client()
    rows = []
    for it in items:
        sql = SafeSQL(args.db)
        t0 = time.time()
        try:
            a = ask(client, it["question"], sql)
            row = dict(status=a.status, correct=grade(a, it["expected"]), attempts=a.attempts,
                       tool_calls=sum(r.tool_calls for r in a.runs),
                       tokens=sum(r.input_tokens + r.output_tokens for r in a.runs),
                       stated=[c.claim["value"] for c in a.checks], answer=a.answer)
        except AgentFailed as e:
            row = dict(status=f"error: {e}", correct=False, attempts=0, tool_calls=0, tokens=0, stated=[], answer="")
        finally:
            sql.close()
        row = dict(id=it["id"], difficulty=it["difficulty"], expected=it["expected"], seconds=round(time.time() - t0, 1), **row)
        rows.append(row)
        print(f"{'PASS' if row['correct'] else 'FAIL'} {it['id']:<28} {row['status']:<14} expected {it['expected']:.6g}")

    df = pd.DataFrame(rows)
    out = ROOT / "evals" / "results"
    out.mkdir(exist_ok=True)
    df.to_csv(out / "latest.csv", index=False)
    verified_wrong = int(((df.status == "verified") & ~df.correct).sum())
    print(f"\n{df.correct.sum()}/{len(df)} correct ({df.correct.mean():.0%}), "
          f"{(df.status == 'verified').mean():.0%} verified, {verified_wrong} verified but wrong")
    print(df.groupby("difficulty").correct.agg(["sum", "count"]).to_string())


if __name__ == "__main__":
    main()
