"""Sanity checks on the data model and the analysis SQL.

Builds a fresh model from a freshly generated sample into a temp folder,
so the tests never depend on files left over from earlier runs.
"""
from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_model import build  # noqa: E402
from run_analysis import run_queries  # noqa: E402


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mkt")
    raw, db = tmp / "raw", tmp / "test.duckdb"
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(raw)],
                   check=True, capture_output=True)
    dq = build(raw, db)
    return dict(db=db, dq=dq, results=run_queries(db), con=duckdb.connect(str(db), read_only=True))


def q(built, sql):
    v = built["con"].execute(sql).fetchone()[0]
    return float(v) if isinstance(v, Decimal) else v  # spend is stored as an exact decimal


def test_cleaning_fixed_every_injected_issue(built):
    assert q(built, "SELECT COUNT(*) FROM fact_ad_daily WHERE spend < 0") == 0
    assert q(built, "SELECT COUNT(*) FROM fact_ad_daily WHERE clicks > impressions") == 0
    assert q(built, "SELECT COUNT(*) - COUNT(DISTINCT lead_id) FROM fact_leads") == 0
    assert q(built, "SELECT COUNT(*) FROM fact_sessions WHERE device IS NULL") == 0
    channels = {r[0] for r in built["con"].execute("SELECT DISTINCT channel FROM fact_sessions").fetchall()}
    assert channels == {r[0] for r in built["con"].execute("SELECT channel FROM dim_channel").fetchall()}
    assert len(channels) == 10
    assert (built["dq"].rows_affected > 0).all()


def test_funnel_never_grows(built):
    f = built["results"]["03_marketing_funnel"]
    assert f.volume.is_monotonic_decreasing
    assert f.step_conversion.dropna().between(0, 1).all()


def test_channel_totals_match_facts(built):
    ch = built["results"]["01_channel_performance"]
    assert ch.spend.sum() == pytest.approx(q(built, "SELECT SUM(spend) FROM fact_ad_daily"), rel=1e-6)
    assert ch.leads.sum() == q(built, "SELECT COUNT(*) FROM fact_leads")
    assert ch.revenue.sum() == pytest.approx(q(built, "SELECT SUM(revenue) FROM fact_leads"), rel=1e-6)
    paid = ch.dropna(subset=["roas"])
    assert (paid.roas - paid.revenue / paid.spend).abs().max() < 0.01


def test_every_customer_revenue_is_attributed(built):
    # revenue in orders == revenue on leads (each paying user is exactly one lead)
    assert q(built, "SELECT SUM(revenue) FROM fact_orders") == pytest.approx(
        q(built, "SELECT SUM(revenue) FROM fact_leads"), rel=1e-6)


def test_attribution_credit_sums_to_one_per_lead(built):
    a = built["results"]["08_attribution_rules"]
    n_leads = q(built, "SELECT COUNT(*) FROM fact_leads")
    n_customers = q(built, "SELECT COUNT(*) FROM fact_leads WHERE is_customer")
    for model, g in a.groupby("model"):
        assert g.leads.sum() == pytest.approx(n_leads, abs=1), model
        assert g.customers.sum() == pytest.approx(n_customers, abs=1), model
        assert g.revenue_share.sum() == pytest.approx(1, abs=1e-3), model


def test_last_touch_matches_lead_source(built):
    a = built["results"]["08_attribution_rules"]
    last = a[a.model == "last_touch"].set_index("channel").leads
    src = built["results"]["01_channel_performance"].set_index("channel").leads
    pd.testing.assert_series_equal(last.sort_index(), src.sort_index().astype(float), check_names=False, atol=0.01)


def test_segments_cover_all_paid_spend(built):
    seg = built["results"]["06_segment_performance"]
    unknown = q(built, "SELECT COUNT(*) FROM fact_ad_daily WHERE device = 'unknown'")
    assert unknown == 0
    assert seg.spend.sum() == pytest.approx(q(built, "SELECT SUM(spend) FROM fact_ad_daily"), rel=1e-6)


def test_journeys_end_at_conversion(built):
    # every lead has at least one touch, and its last touch is the converting session
    assert q(built, "SELECT COUNT(DISTINCT lead_id) FROM fact_journeys") == q(built, "SELECT COUNT(*) FROM fact_leads")
    mismatched = q(built, """
        SELECT COUNT(*) FROM fact_journeys j JOIN fact_leads l USING (lead_id)
        WHERE j.touch_number = j.touches AND j.session_id <> l.session_id""")
    assert mismatched == 0
