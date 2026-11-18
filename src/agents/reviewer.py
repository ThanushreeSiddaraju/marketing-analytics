"""Reviewer agent: does the SQL actually answer the question?

The numbers themselves are checked in code (verify.check_claims). What code
can't catch is a correct number from the wrong query: last touch when the
question asked about first touch, leads counted instead of customers, a filter
that drops half the year. The reviewer gets the question, the answer, and the
SQL and results behind each claim, and has no tools, so it can't wander off.
"""
from __future__ import annotations

from .llm import obj_schema, run_agent
from .sql_tool import SafeSQL

SYSTEM = """\
You review a junior analyst's answer before it goes to the marketing team. The numbers have already been checked against the query results, so don't recompute them. Your job is to decide whether the queries answer the question that was asked.

Fail the answer if, for example:
- the query measures something different from the question (leads vs customers, first vs last touch, spend vs revenue, wrong time period)
- a filter or join drops or double counts rows in a way that changes the answer
- the answer's wording claims more than the numbers show

Pass it if the queries answer the question, even if you'd have written them differently. Be specific in problems: name the query_id and what's wrong. Leave problems empty when it passes.
"""

OUTPUT = obj_schema({
    "verdict": {"type": "string", "enum": ["pass", "fail"]},
    "problems": {"type": "array", "items": {"type": "string"}},
})


def review(client, question: str, answer: dict, sql: SafeSQL, effort: str = "medium") -> dict:
    parts = [f"Question: {question}", f"Answer: {answer['answer']}"]
    if answer.get("caveats"):
        parts.append(f"Caveats: {answer['caveats']}")
    for qid in dict.fromkeys(c["query_id"] for c in answer["claims"]):
        rec = sql.ledger[qid]
        parts.append(f"--- {qid}\n{rec.sql}\nFirst rows:\n{rec.result.head(15).to_csv(index=False)}")
    parts.append("Claims:\n" + "\n".join(f"- {c['statement']}: {c['value']} ({c['query_id']}.{c['column']} row {c['row']})"
                                         for c in answer["claims"]))
    run = run_agent(client, system=SYSTEM, messages=[{"role": "user", "content": "\n\n".join(parts)}],
                    output_schema=OUTPUT, effort=effort)
    return run.output
