"""Sanity tests on the Phase 3 tables built from the real data.
Skipped until the pipeline has been run."""
import sqlite3

import numpy as np
import pytest

from ftselab import config, db


def _has_tables() -> bool:
    if not config.DB_PATH.exists():
        return False
    with sqlite3.connect(config.DB_PATH) as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE name = 'mart_event_results'").fetchone() is not None


pytestmark = pytest.mark.skipif(not _has_tables(), reason="event tables not built; run python run_pipeline.py")


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    yield c
    c.close()


def test_event_counts(conn):
    ev = db.query("SELECT * FROM mart_event_list", conn)
    decisions = db.query("SELECT COUNT(*) n FROM clean_boe_decisions", conn)["n"].iloc[0]
    assert len(ev) == decisions
    inc = ev[ev["included"] == 1]
    # only the earliest 2010 meetings lack a full estimation window
    assert (ev.loc[ev["included"] == 0, "event_date"] < "2011-01-01").all()
    assert len(inc) >= decisions - 12
    assert set(inc["decision"]) == {"hike", "cut", "hold"}


def test_placebo_pool_has_no_event_days(conn):
    pool = set(db.query("SELECT date FROM mart_event_placebo_pool", conn)["date"])
    events = set(db.query("SELECT event_date FROM clean_boe_decisions", conn)["event_date"])
    assert len(pool) > 300
    assert not pool & events


def test_index_car_equals_return_minus_mean(conn):
    """Day-0 CAR for the index (constant-mean model) is close to its raw return,
    because the index's average daily return is tiny."""
    car = db.query("SELECT c.event_date, c.car, r.daily_return FROM mart_event_car c "
                   "JOIN mart_daily_returns r ON r.ticker = c.series AND r.date = c.event_date "
                   f"WHERE c.series = '{config.INDEX_TICKER}' AND c.window = 'day0'", conn)
    assert len(car) > 100
    assert np.abs(car["car"] - car["daily_return"]).max() < 0.002


def test_results_well_formed(conn):
    r = db.query("SELECT * FROM mart_event_results", conn)
    assert r["p_placebo"].dropna().between(0, 1).all()
    assert r["q_fdr_placebo"].dropna().between(0, 1).all()
    assert (r["q_fdr_placebo"].dropna() >= r.loc[r["q_fdr_placebo"].notna(), "p_placebo"] - 1e-12).all()
    assert set(r["window"]) == set(config.EVENT_WINDOWS)
    stock = r[r["kind"] == "stock"]
    assert (stock["n_events"] >= config.EVENT_MIN_EVENTS_STOCK).all()


def test_sector_car_is_relative_to_market(conn):
    """Market-model abnormal returns of the equal-weighted all-stocks portfolio
    should average close to zero over all decisions."""
    r = db.query("SELECT mean FROM mart_event_results WHERE series = 'All stocks (equal weight)' "
                 "AND \"group\" = 'all_scheduled' AND window = 'day0'", conn)
    assert abs(r["mean"].iloc[0]) < 0.002


def test_volatility_table(conn):
    v = db.query("SELECT * FROM mart_event_volatility", conn)
    assert len(v) == 13
    assert (v["variance_ratio"] > 0).all() and v["p_placebo_one_sided"].between(0, 1).all()
