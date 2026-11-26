"""The data contract should pass the real raw files and stop broken ones with a clear message."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_model import build  # noqa: E402
from contracts import ContractError, validate  # noqa: E402


@pytest.fixture(scope="module")
def clean_raw(tmp_path_factory):
    raw = tmp_path_factory.mktemp("contract") / "raw"
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(raw)],
                   check=True, capture_output=True)
    return raw


@pytest.fixture
def raw(clean_raw, tmp_path):
    """A fresh copy each test can break."""
    dst = tmp_path / "raw"
    shutil.copytree(clean_raw, dst)
    return dst


def edit(path: Path, fn):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    fn(df).to_csv(path, index=False)


def problems(raw):
    with pytest.raises(ContractError) as e:
        validate(raw)
    return str(e.value)


def test_generated_data_passes(clean_raw):
    validate(clean_raw)


def test_planted_quality_issues_are_not_contract_breaks(clean_raw):
    # negative spend, odd channel names and duplicate leads are cleaning's job, not the contract's
    ad = pd.read_csv(clean_raw / "ad_daily.csv")
    assert (ad.spend < 0).any()
    validate(clean_raw)


def test_renamed_column(raw):
    edit(raw / "ad_daily.csv", lambda d: d.rename(columns={"spend": "cost"}))
    assert "ad_daily.csv: missing column 'spend'" in problems(raw)


def test_unparseable_values(raw):
    def bad(d):
        d.loc[:4, "impressions"] = "n/a"
        return d
    edit(raw / "ad_daily.csv", bad)
    assert "ad_daily.csv.impressions: 5 value(s) aren't a valid bigint" in problems(raw)


def test_blank_ids(raw):
    def bad(d):
        d.loc[:2, "lead_id"] = ""
        return d
    edit(raw / "leads.csv", bad)
    assert "leads.csv.lead_id: 3 blank value(s) in a required column" in problems(raw)


def test_dates_from_the_wrong_year(raw):
    def bad(d):
        d.loc[:9, "order_date"] = "2019-03-01"
        return d
    edit(raw / "orders.csv", bad)
    assert "orders.csv.order_date: 10 date(s) outside 2025-01-01 to 2025-12-31" in problems(raw)


def test_every_problem_is_reported_at_once(raw):
    (raw / "creatives.csv").unlink()
    edit(raw / "sessions.csv", lambda d: d.drop(columns=["ts"]))
    msg = problems(raw)
    assert "creatives.csv: file is missing" in msg and "sessions.csv: missing column 'ts'" in msg


def test_build_stops_before_loading_a_broken_file(raw, tmp_path):
    edit(raw / "campaigns.csv", lambda d: d.drop(columns=["channel"]))
    with pytest.raises(ContractError):
        build(raw, tmp_path / "x.duckdb")
    assert not (tmp_path / "x.duckdb").exists()
