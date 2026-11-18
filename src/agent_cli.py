"""Run the agents from the command line. Needs ANTHROPIC_API_KEY.

  python src/agent_cli.py ask "Which paid channel had the lowest CAC?"
  python src/agent_cli.py quality          # data quality report on the raw tables
  python src/agent_cli.py brief            # answer a fixed set of questions and write a brief

Results are saved to output/agents/. Build the database first with
python src/run_analysis.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents.analyst import ask  # noqa: E402
from agents.data_quality import inspect  # noqa: E402
from agents.llm import make_client  # noqa: E402
from agents.sql_tool import SafeSQL  # noqa: E402
from agents.writer import write_brief  # noqa: E402

BRIEF_QUESTIONS = [
    "Which paid channels had the best and worst CAC in 2025, and how far apart were they?",
    "What share of the total ad budget went to Google Display and TikTok combined, and how many customers did they bring in?",
    "At which funnel stage do we lose the most leads after they become a lead?",
    "How does the lead-to-customer conversion rate on mobile compare with desktop?",
    "Which ad offer type has the highest click-through rate?",
]


def show_answer(a, sql) -> dict:
    print(f"\n{a.question}\n  [{a.status}, attempt {a.attempts}] {a.answer}")
    for c in a.checks:
        print(f"    {'ok ' if c.ok else 'BAD'} {c.claim['statement']}: {c.claim['value']} ({c.reason})")
    for p in a.review.get("problems", []):
        print(f"    reviewer: {p}")
    return dict(question=a.question, status=a.status, answer=a.answer, caveats=a.caveats, attempts=a.attempts,
                claims=[dict(c.claim, actual=c.actual, ok=c.ok) for c in a.checks], review=a.review, sql=a.sql_used(sql))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ask", "quality", "brief"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "marketing.duckdb")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "agents")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    client, sql = make_client(), SafeSQL(args.db)

    if args.command == "ask":
        if not args.question:
            ap.error("ask needs a question")
        print(json.dumps(show_answer(ask(client, args.question, sql), sql), indent=2, default=str))

    elif args.command == "quality":
        rep = inspect(client, sql)
        print(rep.summary)
        for i, c in zip(rep.issues, rep.checks):
            print(f"  {'ok ' if c.ok else 'BAD'} {i['table']}: {i['problem']} ({i['rows_affected']:g} rows) -> {i['fix']}")
        (args.out / "data_quality.json").write_text(json.dumps(
            dict(summary=rep.summary, issues=[dict(i, count_checked=c.ok) for i, c in zip(rep.issues, rep.checks)]),
            indent=2, default=str))

    else:
        answers = [ask(client, q, sql) for q in BRIEF_QUESTIONS]
        records = [show_answer(a, sql) for a in answers]
        brief = write_brief(client, answers)
        (args.out / "answers.json").write_text(json.dumps(records, indent=2, default=str))
        (args.out / "brief.md").write_text(brief.markdown())
        print("\n" + brief.markdown())
        if not brief.checked:
            print(f"Brief has numbers that couldn't be traced: {brief.unsupported_numbers}")
    sql.close()


if __name__ == "__main__":
    main()
