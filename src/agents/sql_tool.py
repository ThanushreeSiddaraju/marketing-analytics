"""The only way the agents touch data: one read-only SELECT at a time.

Two layers, so a mistake in one doesn't open anything up:

1. sqlglot parses the query first. It has to be exactly one SELECT (CTEs and
   UNIONs are fine), it can only read tables on the allowlist, and it can't
   call anything that reads files or changes settings.
2. DuckDB itself is opened read-only with external access off and the
   configuration locked, so even if something slipped past the parser it
   couldn't read a file, write, attach another database or turn access back on.

Every query that runs gets an id (q1, q2, ...) and its SQL and result are kept
in a ledger. Agents have to cite those ids for every number they state, and the
checker re-runs the SQL to make sure the number is really there.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

MAX_ROWS = 200
TIMEOUT_S = 10.0

MODEL_TABLES = {
    "dim_date", "dim_channel", "dim_campaign", "dim_creative",
    "fact_ad_daily", "fact_sessions", "fact_leads", "fact_orders", "fact_journeys",
}
RAW_TABLES = {"raw_ad_daily", "raw_campaigns", "raw_creatives", "raw_leads", "raw_orders", "raw_sessions"}

BLOCKED_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Pragma, exp.Copy, exp.Set, exp.Use, exp.Attach, exp.Detach,
    exp.Install, exp.Into, exp.Transaction, exp.Commit, exp.Rollback,
)
BLOCKED_FUNCTION_PREFIXES = ("read_", "glob", "parquet_", "sniff_", "duckdb_", "pragma_", "query",
                             "iceberg_", "delta_", "http", "load", "install", "getenv", "current_setting",
                             "sqlite_", "postgres_", "mysql_")


class QueryRejected(ValueError):
    """The query isn't allowed. The message is shown to the agent so it can fix it."""


def check_sql(sql: str, allowed_tables: set[str]) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise QueryRejected(f"could not parse the query: {str(e).splitlines()[0]}") from None
    if len(statements) != 1:
        raise QueryRejected("send exactly one statement")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise QueryRejected("only SELECT queries are allowed")
    for node in tree.walk():
        if isinstance(node, BLOCKED_NODES):
            raise QueryRejected(f"{type(node).__name__.upper()} is not allowed")
        if isinstance(node, exp.Func):
            name = (node.sql_name() if not isinstance(node, exp.Anonymous) else node.name).lower()
            if name.startswith(BLOCKED_FUNCTION_PREFIXES):
                raise QueryRejected(f"function {name}() is not allowed")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if isinstance(t.this, exp.Func) or not t.name:
            raise QueryRejected("table functions are not allowed, query a table by name")
        if t.args.get("db") or t.args.get("catalog"):
            raise QueryRejected("use plain table names without a schema or database prefix")
        name = t.name.lower()
        if name not in allowed_tables and name not in ctes:
            raise QueryRejected(f"unknown table {name!r}; available: {', '.join(sorted(allowed_tables))}")
    return tree


@dataclass
class QueryRecord:
    query_id: str
    sql: str
    result: pd.DataFrame
    truncated: bool


@dataclass
class SafeSQL:
    db: Path
    allowed_tables: set[str] = field(default_factory=lambda: set(MODEL_TABLES))
    max_rows: int = MAX_ROWS
    timeout_s: float = TIMEOUT_S
    ledger: dict[str, QueryRecord] = field(default_factory=dict)

    def __post_init__(self):
        self.con = duckdb.connect(str(self.db), read_only=True, config={
            "enable_external_access": False,
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            "lock_configuration": True,
        })

    def close(self):
        self.con.close()

    def _execute(self, sql: str) -> tuple[pd.DataFrame, bool]:
        timer = threading.Timer(self.timeout_s, self.con.interrupt)
        timer.start()
        try:
            cur = self.con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(self.max_rows + 1)
        except duckdb.InterruptException:
            raise QueryRejected(f"query took longer than {self.timeout_s:.0f}s and was stopped") from None
        finally:
            timer.cancel()
        return pd.DataFrame(rows[: self.max_rows], columns=cols), len(rows) > self.max_rows

    def run(self, sql: str) -> QueryRecord:
        check_sql(sql, self.allowed_tables)
        try:
            df, truncated = self._execute(sql)
        except duckdb.Error as e:
            raise QueryRejected(f"DuckDB error: {str(e).splitlines()[0]}") from None
        rec = QueryRecord(f"q{len(self.ledger) + 1}", sql, df, truncated)
        self.ledger[rec.query_id] = rec
        return rec

    def rerun(self, query_id: str) -> pd.DataFrame:
        """Run a ledger query again from its SQL (used by the checker)."""
        return self._execute(self.ledger[query_id].sql)[0]

    def schema(self) -> str:
        """Column names and types for every allowed table, for the system prompt."""
        tables = ", ".join(f"'{t}'" for t in sorted(self.allowed_tables))
        df = self.con.execute(f"""
            SELECT table_name, string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position)
            FROM information_schema.columns WHERE table_name IN ({tables})
            GROUP BY table_name ORDER BY table_name""").fetchall()
        return "\n".join(f"{t}({cols})" for t, cols in df)


def format_result(rec: QueryRecord, max_chars: int = 6000) -> str:
    text = rec.result.to_csv(index=False)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(cut)"
    note = f" (first {len(rec.result)} rows only)" if rec.truncated else ""
    return f"query_id={rec.query_id}, {len(rec.result)} rows{note}\n{text}"
