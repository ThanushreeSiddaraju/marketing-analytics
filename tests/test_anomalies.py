"""The anomaly check should find the problems planted in the sample data and not much else."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anomalies  # noqa: E402
from build_model import build  # noqa: E402


def test_robust_score_flags_a_spike_but_not_noise():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + rng.normal(0, 2, 60))
    s.iloc[45] = 160
    _, z = anomalies.robust_scores(s)
    assert abs(z.iloc[45]) > anomalies.THRESHOLD
    assert (z.drop(45).abs() > anomalies.THRESHOLD).sum() == 0


@pytest.fixture(scope="module")
def episodes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("anom")
    subprocess.run([sys.executable, str(ROOT / "src" / "make_sample_data.py"), "--out", str(tmp / "raw")],
                   check=True, capture_output=True)
    build(tmp / "raw", tmp / "a.duckdb")
    return anomalies.run(tmp / "a.duckdb")["16_anomaly_episodes"]


def find(ep, channel, metric):
    return ep[(ep.channel == channel) & (ep.metric == metric)]


def test_finds_the_meta_tracking_outage(episodes):
    meta = find(episodes, "Meta Ads", "ctr")
    hit = meta[(meta.direction == "low") & (meta.start == "2025-03-10")]
    assert len(hit) == 1 and hit.end.iloc[0] == pd.Timestamp("2025-03-16")


def test_finds_spend_with_no_impressions(episodes):
    d = find(episodes, "Google Display", "impr_per_dollar")
    assert (d.start == "2025-08-14").any()


def test_finds_the_linkedin_cpm_jump(episodes):
    li = find(episodes, "LinkedIn Ads", "cpm")
    assert ((li.direction == "high") & (li.start == "2025-10-01")).any()


def test_not_too_many_false_alarms(episodes):
    planted = {("Meta Ads", "ctr"), ("Google Display", "impr_per_dollar"), ("LinkedIn Ads", "cpm"), ("LinkedIn Ads", "impr_per_dollar")}
    other = episodes[~episodes.apply(lambda r: (r.channel, r.metric) in planted, axis=1)]
    # a few one-day blips across 6 channels x 3 metrics x 365 days is fine; a flood isn't
    assert len(other) <= 10
    assert (other.days == 1).all()
