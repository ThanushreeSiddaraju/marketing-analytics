"""Offline tests for the agents.

No API key needed: a fake client plays back scripted model turns, so these test
the plumbing around the model (the SQL guard, the tool loop, the ledger, the
claim checks and the writer's number check), which is where the safety lives.
How good the real model is at the questions is measured by evals/run_evals.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents import analyst, data_quality, writer  # noqa: E402
from agents.llm import AgentFailed  # noqa: E402
from agents.sql_tool import QueryRejected, SafeSQL  # noqa: E402
from agents.verify import check_text, close_enough, numbers_in  # noqa: E402
from build_model import build  # noqa: E402


# ---------------------------------------------------------------- fake model

def tool_call(sql, id_="t1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=id_, name="run_sql", input={"sql": sql})],
              usage=NS(input_tokens=10, output_tokens=5))


def final(obj):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(obj))],
              usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    """Plays back responses in order. Each item is a response or a function of
    the request kwargs that returns one. Requests are kept for assertions."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        nxt = self.script.pop(0)
        return nxt(kwargs) if callable(nxt) else nxt


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("agents")
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(tmp / "raw")],
                   check=True, capture_output=True)
    build(tmp / "raw", tmp / "a.duckdb")
    return tmp / "a.duckdb"


@pytest.fixture
def sql(db):
    s = SafeSQL(db)
    yield s
    s.close()


SPEND_BY_CHANNEL = "SELECT channel, SUM(spend) AS spend FROM fact_ad_daily GROUP BY 1 ORDER BY spend DESC"
PASS = final({"verdict": "pass", "problems": []})


# ---------------------------------------------------------------- SQL guard

@pytest.mark.parametrize("bad", [
    "DROP TABLE fact_leads",
    "SELECT 1; SELECT 2",
    "DELETE FROM fact_leads",
    "SELECT * FROM read_csv_auto('data/raw/leads.csv')",
    "SELECT * FROM 'data/raw/leads.csv'",
    "COPY fact_leads TO 'leak.csv'",
    "ATTACH 'other.duckdb'",
    "PRAGMA database_list",
    "SET enable_external_access = true",
    "SELECT getenv('HOME')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * INTO leak FROM fact_leads",
    "SELECT * FROM raw_leads",
    "SELECT * FROM main.fact_leads",
])
def test_guard_rejects(sql, bad):
    with pytest.raises(QueryRejected):
        sql.run(bad)
    assert sql.ledger == {}


def test_guard_allows_normal_analysis(sql):
    rec = sql.run("""
        WITH c AS (SELECT channel, COUNT(*) FILTER (WHERE is_customer) AS customers FROM fact_leads GROUP BY 1)
        SELECT channel, customers, RANK() OVER (ORDER BY customers DESC) AS rnk FROM c""")
    assert rec.query_id == "q1" and len(rec.result) == 10


def test_database_layer_blocks_files_even_without_the_parser(sql):
    # skip the parser and go straight at the connection
    with pytest.raises(Exception):
        sql.con.execute("SELECT * FROM read_csv_auto('data/raw/leads.csv')")
    with pytest.raises(Exception):
        sql.con.execute("SET enable_external_access = true")


def test_row_cap(sql):
    rec = sql.run("SELECT * FROM fact_sessions")
    assert len(rec.result) == sql.max_rows and rec.truncated


# ---------------------------------------------------------------- number checks

def test_close_enough_handles_rounding_and_percentages():
    assert close_enough(101391, 101390.95)
    assert close_enough(14.2, 0.1416)
    assert close_enough(1.14, 1.1411)
    assert not close_enough(1.3, 1.1411)
    assert not close_enough(15, 0.1416)


def test_numbers_in_text():
    got = [v for _, v in numbers_in("Search cost $101.4k, ROAS 1.32x, 14% of leads and 1,607 leads in 2025")]
    assert got == [101400, 1.32, 14, 1607, 2025]


def test_check_text_flags_made_up_numbers():
    verified = [101390.95, 0.1416, 1607]
    assert check_text("Search spend was $101.4k and Meta brought 1,607 leads (14%).", verified) == []
    assert check_text("Search spend was $120k.", verified) == ["$120k"]


# ---------------------------------------------------------------- analyst loop

def test_analyst_answer_is_checked_against_the_database(sql):
    client = FakeClient([
        tool_call(SPEND_BY_CHANNEL),
        final({"answer": "Google Search had the most spend, about $101.4k.", "caveats": "",
               "claims": [{"statement": "Google Search spend", "value": 101391, "query_id": "q1", "column": "spend", "row": 0}]}),
        PASS,
    ])
    a = analyst.ask(client, "Which channel had the most spend?", sql)
    assert a.status == "verified" and a.attempts == 1
    assert a.checks[0].actual == pytest.approx(101390.95, rel=1e-6)
    # the tool result went back to the model with the query id
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and tool_result["content"].startswith("query_id=q1")
    # strict tools and structured output are on every request
    assert client.requests[0]["tools"][0]["strict"] is True
    assert client.requests[0]["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in client.requests[0]


def test_wrong_number_is_caught_and_sent_back(sql):
    client = FakeClient([
        tool_call(SPEND_BY_CHANNEL),
        final({"answer": "Search spend was $150k.", "caveats": "",
               "claims": [{"statement": "Google Search spend", "value": 150000, "query_id": "q1", "column": "spend", "row": 0}]}),
        # second attempt, after the feedback
        lambda kw: final({"answer": "Search spend was $101.4k.", "caveats": "",
                          "claims": [{"statement": "Google Search spend", "value": 101390.95, "query_id": "q1", "column": "spend", "row": 0}]}),
        PASS,
    ])
    a = analyst.ask(client, "How much went on Google Search?", sql)
    assert a.status == "verified" and a.attempts == 2
    feedback = client.requests[2]["messages"][-1]["content"]
    assert "stated 150000" in feedback


def test_citing_a_query_that_never_ran_fails(sql):
    client = FakeClient([
        final({"answer": "We spent $309k.", "caveats": "",
               "claims": [{"statement": "total spend", "value": 309183, "query_id": "q7", "column": "spend", "row": 0}]}),
        final({"answer": "We spent $309k.", "caveats": "",
               "claims": [{"statement": "total spend", "value": 309183, "query_id": "q7", "column": "spend", "row": 0}]}),
    ])
    a = analyst.ask(client, "Total spend?", sql)
    assert a.status == "failed checks" and "not a query that was run" in a.checks[0].reason


def test_reviewer_can_reject_a_correct_number_from_the_wrong_query(sql):
    claim = {"statement": "Meta leads", "value": 1607, "query_id": "q1", "column": "n", "row": 0}
    client = FakeClient([
        tool_call("SELECT COUNT(*) AS n FROM fact_leads WHERE channel = 'Meta Ads'"),
        final({"answer": "Meta was the first touch for 1,607 leads.", "caveats": "", "claims": [claim]}),
        final({"verdict": "fail", "problems": ["q1 counts last-touch leads, the question asked about first touch"]}),
        final({"answer": "Meta was the first touch for 1,607 leads.", "caveats": "", "claims": [claim]}),
        final({"verdict": "fail", "problems": ["still last touch"]}),
    ])
    a = analyst.ask(client, "How many leads had Meta as their first touch?", sql)
    assert a.status == "failed checks" and not a.verified
    assert "reviewer: q1 counts last-touch" in client.requests[3]["messages"][-1]["content"]


def test_bad_sql_goes_back_as_a_tool_error(sql):
    client = FakeClient([
        tool_call("DROP TABLE fact_leads"),
        final({"answer": "I can't change the data.", "caveats": "", "claims": []}),
    ])
    a = analyst.ask(client, "Delete the leads table", sql)
    err = client.requests[1]["messages"][-1]["content"][0]
    assert err["is_error"] is True and "only SELECT" in err["content"]
    assert a.status == "no numbers" and sql.ledger == {}


def test_refusal_and_runaway_loops_stop(sql):
    with pytest.raises(AgentFailed):
        analyst.ask(FakeClient([NS(stop_reason="refusal", content=[], usage=None)]), "x", sql)
    with pytest.raises(AgentFailed):
        analyst.ask(FakeClient([tool_call("SELECT 1 AS x", f"t{i}") for i in range(20)]), "x", sql)


# ---------------------------------------------------------------- data quality and writer

def test_data_quality_counts_are_checked(sql):
    neg = "SELECT COUNT(*) AS n FROM raw_ad_daily WHERE spend < 0"
    client = FakeClient([
        tool_call(neg),
        final({"summary": "Negative spend in the ad export.", "issues": [
            {"table": "raw_ad_daily", "problem": "negative spend", "rows_affected": 15, "query_id": "q1",
             "column": "n", "row": 0, "impact": "understates spend", "fix": "take the absolute value"},
            {"table": "raw_leads", "problem": "made-up issue", "rows_affected": 999, "query_id": "q1",
             "column": "n", "row": 0, "impact": "-", "fix": "-"}]}),
    ])
    rep = data_quality.inspect(client, sql)
    assert [c.ok for c in rep.checks] == [True, False]
    assert len(rep.confirmed) == 1


def test_writer_only_sees_verified_answers_and_numbers_are_traced(sql):
    client = FakeClient([
        tool_call(SPEND_BY_CHANNEL),
        final({"answer": "Search had the most spend.", "caveats": "",
               "claims": [{"statement": "Google Search spend", "value": 101390.95, "query_id": "q1", "column": "spend", "row": 0}]}),
        PASS,
        final({"headline": "Search is the biggest line", "paragraphs": ["Search spend hit $130k."]}),
        final({"headline": "Search is the biggest line", "paragraphs": ["Search spend was about $101k this year."]}),
    ])
    a = analyst.ask(client, "Biggest channel by spend?", sql)
    brief = writer.write_brief(client, [a])
    assert brief.checked and "$101k" in brief.markdown()
    assert "$130k" in client.requests[4]["messages"][-1]["content"]
