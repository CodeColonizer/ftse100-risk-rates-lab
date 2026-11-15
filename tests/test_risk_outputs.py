"""Sanity tests on the Phase 2 output tables built from the real data.

These catch a broken calculation that unit tests miss, e.g. a volatility in
percent rather than a fraction. Skipped until the pipeline has been run.
"""
import sqlite3

import pytest

from ftselab import config, db


def _has_marts() -> bool:
    if not config.DB_PATH.exists():
        return False
    with sqlite3.connect(config.DB_PATH) as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE name = 'mart_stock_risk'").fetchone() is not None


pytestmark = pytest.mark.skipif(not _has_marts(), reason="risk tables not built; run python run_pipeline.py")


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    yield c
    c.close()


def test_every_stock_and_index_has_metrics(conn):
    s = db.query("SELECT * FROM mart_stock_risk", conn)
    n = db.query("SELECT COUNT(*) n FROM clean_constituents", conn)["n"].iloc[0]
    assert len(s) == n + 1
    assert s[["ann_volatility", "beta", "sharpe", "max_drawdown"]].notna().all().all()


def test_metrics_in_plausible_ranges(conn):
    s = db.query("SELECT * FROM mart_stock_risk", conn)
    assert s["ann_volatility"].between(0.05, 1.0).all()
    assert s["max_drawdown"].between(-1, 0).all()
    assert s["beta"].between(-0.5, 3).all()
    assert s["sharpe"].between(-2, 3).all()


def test_index_beta_is_one(conn):
    idx = db.query("SELECT beta, corr_with_index FROM mart_stock_risk WHERE ticker = :t", conn,
                   t=config.INDEX_TICKER)
    assert idx["beta"].iloc[0] == pytest.approx(1.0)
    assert idx["corr_with_index"].iloc[0] == pytest.approx(1.0)


def test_sector_table_covers_all_industries(conn):
    s = db.query("SELECT sector FROM mart_sector_risk", conn)["sector"].tolist()
    industries = db.query("SELECT DISTINCT icb_industry FROM clean_constituents", conn)["icb_industry"]
    assert set(industries) <= set(s)


def test_correlation_matrix_is_symmetric_with_unit_diagonal(conn):
    c = db.query("SELECT * FROM mart_sector_correlation", conn)
    wide = c.pivot(index="sector_a", columns="sector_b", values="correlation")
    assert list(wide.values.diagonal()) == pytest.approx([1.0] * len(wide))
    assert abs(wide - wide.T).max().max() < 1e-12
    assert c["correlation"].between(-1, 1).all()


def test_rolling_correlations_bounded(conn):
    r = db.query("SELECT corr_with_index FROM mart_rolling_sector_corr", conn)
    assert len(r) > 0 and r["corr_with_index"].between(-1, 1).all()


def test_stress_periods_present_and_index_matches_prices(conn):
    st = db.query("SELECT * FROM mart_stress_periods WHERE kind = 'index'", conn)
    assert set(st["period"]) == {p["period"] for p in config.STRESS_PERIODS}
    for p in config.STRESS_PERIODS:
        px = db.query(
            f"SELECT date, adj_close FROM clean_prices WHERE ticker = '{config.INDEX_TICKER}' "
            f"AND date IN ('{p['base_date']}', '{p['end_date']}') ORDER BY date", conn)
        assert len(px) == 2, f"{p['period']}: base or end date is not a trading day"
        expected = px["adj_close"].iloc[1] / px["adj_close"].iloc[0] - 1
        got = st.loc[st["period"] == p["period"], "window_return"].iloc[0]
        assert got == pytest.approx(expected, rel=1e-9)


def test_covid_window_was_a_crash(conn):
    st = db.query("SELECT window_return FROM mart_stress_periods "
                  "WHERE kind = 'index' AND period = 'covid_crash'", conn)
    assert st["window_return"].iloc[0] < -0.25


def test_daily_returns_match_prices(conn):
    one = db.query(f"SELECT date, daily_return FROM mart_daily_returns WHERE ticker = 'AZN.L' "
                   "ORDER BY date LIMIT 5", conn)
    px = db.query("SELECT date, adj_close FROM clean_prices WHERE ticker = 'AZN.L' ORDER BY date LIMIT 6", conn)
    expected = (px["adj_close"] / px["adj_close"].shift(1) - 1).iloc[1:].tolist()
    assert one["daily_return"].tolist() == pytest.approx(expected)
