"""Data quality agent: looks through the raw tables and reports what's wrong.

It gets the same SQL tool as the analyst, but pointed at the raw_* tables as
they came in, plus the cleaned fact tables to compare against. Every issue it
reports has a row count that cites a query, and that count is checked the same
way as the analyst's numbers.

The generated data has known problems planted in it, so recall is easy to
measure: how many of the planted problems did it find, with the right count?
"""
from __future__ import annotations

from dataclasses import dataclass

from .analyst import sql_tool
from .llm import AgentRun, obj_schema, run_agent
from .sql_tool import MODEL_TABLES, RAW_TABLES, SafeSQL
from .verify import ClaimCheck, check_claims

SYSTEM = """\
You check incoming marketing data before anyone builds reports on it. The raw_* tables are exactly what came out of the ad platforms, the website and the CRM. The fact_* and dim_* tables are the cleaned versions.

Tables:
{schema}

Look for the kinds of problems that break marketing reports: duplicate rows, impossible values (negative spend, more clicks than impressions), missing values, inconsistent category labels, spend with no delivery, records that should be unique but aren't, dates outside the expected range. Use run_sql to look; don't guess.

For each problem you find, report the table, what's wrong, how many rows are affected, why it matters for the numbers, and how to fix it. The rows_affected count must come from a query: give the query_id, the column holding the count, and its 0-based row. Only report problems you confirmed with a query. Order them by how much they'd distort spend, lead or revenue numbers.
"""

ISSUE = obj_schema({
    "table": {"type": "string"},
    "problem": {"type": "string"},
    "rows_affected": {"type": "number"},
    "query_id": {"type": "string"},
    "column": {"type": "string"},
    "row": {"type": "integer"},
    "impact": {"type": "string"},
    "fix": {"type": "string"},
})
OUTPUT = obj_schema({"summary": {"type": "string"}, "issues": {"type": "array", "items": ISSUE}})


@dataclass
class QualityReport:
    summary: str
    issues: list[dict]
    checks: list[ClaimCheck]
    run: AgentRun

    @property
    def confirmed(self) -> list[dict]:
        return [i for i, c in zip(self.issues, self.checks, strict=True) if c.ok]


def inspect(client, sql: SafeSQL, effort: str = "high") -> QualityReport:
    sql.allowed_tables = set(RAW_TABLES) | set(MODEL_TABLES)
    run = run_agent(client, system=SYSTEM.format(schema=sql.schema()),
                    messages=[{"role": "user", "content": "Check the raw data and report every problem you can confirm."}],
                    output_schema=OUTPUT, tools=[sql_tool(sql)], effort=effort, max_turns=25)
    issues = run.output["issues"]
    claims = [dict(statement=i["problem"], value=i["rows_affected"], query_id=i["query_id"],
                   column=i["column"], row=i["row"]) for i in issues]
    return QualityReport(run.output["summary"], issues, check_claims(claims, sql), run)
