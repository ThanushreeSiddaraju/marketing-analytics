"""Analyst agent: answers a marketing question by writing SQL.

It can only see the data through the run_sql tool, and its final answer is a
JSON object where every number is a claim pointing at a query id, a column and
a row. ask() then checks those claims by re-running the SQL, has the reviewer
look at whether the SQL answers the question, and gives the analyst one chance
to fix anything that failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .llm import AgentRun, Tool, ToolError, obj_schema, run_agent
from .reviewer import review
from .sql_tool import QueryRejected, SafeSQL, format_result
from .verify import ClaimCheck, check_claims

DEFINITIONS = """\
How the business numbers are defined in this database (Lumora, a B2B SaaS, calendar year 2025):
- Spend, impressions and clicks are in fact_ad_daily. Only paid channels have spend; Email has a small send cost.
- A lead is a row in fact_leads. fact_leads.channel is the last-touch channel (the visit where they filled in the form).
- Customers are leads with is_customer = true. fact_leads.revenue is revenue collected in 2025 from that customer.
- CAC = spend / customers, CPL = spend / leads, ROAS = revenue / spend, CTR = clicks / impressions, CPC = spend / clicks.
- Funnel stages on fact_leads: is_mql, is_sql, is_customer.
- fact_journeys has every visit a lead made up to their conversion (touch_number 1..touches), for first-touch questions.
- Monthly orders/invoices are in fact_orders; MRR at signup is fact_leads.mrr.
"""

SYSTEM = """\
You are a marketing analyst answering questions about Lumora's marketing data. You can only look at the data with the run_sql tool, which runs one read-only DuckDB SELECT and gives you back a query_id with the result.

{definitions}
Tables:
{schema}

Work like this:
- Write the SQL that answers the question directly. Compute ratios in SQL rather than in your head, and give columns clear names.
- If a query errors, read the message and fix it.
- Every number in your answer must come from a query result. For each one, add a claim with the query_id, the exact column name, the 0-based row index in that result, and the value as shown there (you may round it, or write a 0-1 share as a percentage).
- Don't state numbers you didn't query. If the data can't answer the question, say so in the answer and leave claims empty.
- Keep the answer short and plain: two to four sentences, the way you'd say it to a marketing manager.
"""

CLAIM = obj_schema({
    "statement": {"type": "string", "description": "the sentence fragment this number supports"},
    "value": {"type": "number"},
    "query_id": {"type": "string"},
    "column": {"type": "string"},
    "row": {"type": "integer"},
})
OUTPUT = obj_schema({
    "answer": {"type": "string"},
    "claims": {"type": "array", "items": CLAIM},
    "caveats": {"type": "string", "description": "assumptions or limits worth mentioning, or empty"},
})


def sql_tool(sql: SafeSQL) -> Tool:
    def fn(args: dict) -> str:
        try:
            return format_result(sql.run(args["sql"]))
        except QueryRejected as e:
            raise ToolError(str(e)) from None

    return Tool(
        name="run_sql",
        description=f"Run one read-only DuckDB SELECT against the marketing tables. Returns a query_id and up to {sql.max_rows} rows as CSV.",
        input_schema=obj_schema({"sql": {"type": "string", "description": "a single SELECT statement"}}),
        fn=fn,
    )


@dataclass
class Answer:
    question: str
    answer: str
    claims: list[dict]
    caveats: str
    checks: list[ClaimCheck]
    review: dict
    attempts: int
    runs: list[AgentRun] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.claims) and all(c.ok for c in self.checks) and self.review.get("verdict") == "pass"

    @property
    def status(self) -> str:
        if self.verified:
            return "verified"
        if not self.claims:
            return "no numbers"
        return "failed checks"

    def sql_used(self, sql: SafeSQL) -> dict[str, str]:
        return {q: sql.ledger[q].sql for q in dict.fromkeys(c["query_id"] for c in self.claims) if q in sql.ledger}


def ask(client, question: str, sql: SafeSQL, max_attempts: int = 2, effort: str = "high") -> Answer:
    system = SYSTEM.format(definitions=DEFINITIONS, schema=sql.schema())
    messages = [{"role": "user", "content": question}]
    runs = []
    for attempt in range(1, max_attempts + 1):
        run = run_agent(client, system=system, messages=messages, output_schema=OUTPUT,
                        tools=[sql_tool(sql)], effort=effort)
        runs.append(run)
        out = run.output
        checks = check_claims(out["claims"], sql)
        failed = [c for c in checks if not c.ok]
        verdict = review(client, question, out, sql) if out["claims"] and not failed else \
            {"verdict": "fail" if failed else "pass", "problems": []}
        ans = Answer(question, out["answer"], out["claims"], out.get("caveats", ""), checks, verdict, attempt, runs)
        if ans.verified or not out["claims"] or attempt == max_attempts:
            return ans
        feedback = [f"- claim '{c.claim['statement']}': {c.reason}" for c in failed]
        feedback += [f"- reviewer: {p}" for p in verdict.get("problems", [])]
        messages.append({"role": "user", "content":
                         "Your answer didn't pass the checks:\n" + "\n".join(feedback) +
                         "\nFix the SQL or the numbers and give the full answer again."})
    return ans
