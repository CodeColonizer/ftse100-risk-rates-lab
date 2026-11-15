"""Tests for the Streamlit app and the data it publishes.

Skipped until the pipeline has built app/data/ (python run_pipeline.py).
The daily GitHub Actions job runs them after every rebuild, before publishing.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
DATA = ROOT / "app" / "data"

pytestmark = pytest.mark.skipif(not (DATA / "meta.json").exists(),
                                reason="app data not built; run python run_pipeline.py")


def test_no_raw_prices_published():
    """The app data must not contain raw price data (project rule)."""
    raw_like = {"open", "high", "low", "close", "adj_close", "volume"}
    for f in DATA.glob("*.csv"):
        cols = set(pd.read_csv(f, nrows=0).columns)
        assert not cols & raw_like, f"{f.name} has raw price columns {cols & raw_like}"


def test_app_data_small_and_complete():
    size_mb = sum(p.stat().st_size for p in DATA.glob("*")) / 1e6
    assert size_mb < 5
    expected = {"sector_risk", "stock_risk", "sector_growth", "sector_correlation", "rolling_corr",
                "stress_periods", "stress_definitions", "event_results", "event_volatility",
                "event_path", "boe_decisions", "quality_report", "event_stock_results"}
    assert expected <= {p.stem for p in DATA.glob("*.csv")}


def test_meta_consistent():
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    assert meta["quality"]["failed"] == 0
    assert meta["n_decisions_analysed"] <= meta["n_decisions_total"]
    assert meta["data_through"] >= "2026-01-01"


def test_growth_series_start_at_100():
    g = pd.read_csv(DATA / "sector_growth.csv")
    first = g.sort_values("date").groupby("series")["growth_of_100"].first()
    assert (first.between(90, 110)).all()   # first weekly point is within days of the start


def test_app_runs_without_errors():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 6
    assert any("Key findings" in s.value for s in at.subheader)
