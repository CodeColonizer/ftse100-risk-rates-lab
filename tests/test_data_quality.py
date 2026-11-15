"""Data quality tests on the real database built by run_pipeline.py.

Skipped if the database has not been built yet. 'error' checks must pass;
'warning' checks only report rows for review, so they never fail the suite.
"""
import pytest

from ftselab import config, db, quality

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="database not built; run python run_pipeline.py")

ERROR_CHECKS = [c for c in quality.CHECKS if c.severity == "error"]


@pytest.fixture(scope="module")
def conn():
    c = db.connect()
    yield c
    c.close()


@pytest.mark.parametrize("check", ERROR_CHECKS, ids=[c.name for c in ERROR_CHECKS])
def test_error_check_passes(conn, check):
    failing = db.query(check.sql, conn)
    assert failing.empty, f"{check.description}: {len(failing)} rows, e.g.\n{failing.head(10)}"


def test_every_constituent_and_index_loaded(conn):
    tickers = set(db.query("SELECT DISTINCT ticker FROM clean_prices", conn)["ticker"])
    expected = set(db.query("SELECT ticker FROM clean_constituents", conn)["ticker"])
    assert config.INDEX_TICKER in tickers
    assert expected <= tickers


def test_decision_mix_is_plausible(conn):
    counts = db.query("SELECT decision, COUNT(*) n FROM clean_boe_decisions GROUP BY decision",
                      conn).set_index("decision")["n"]
    # Since 2010 the MPC has held far more often than it has moved.
    assert counts["hold"] > counts["hike"] + counts["cut"]
    assert counts["hike"] >= 10 and counts["cut"] >= 5
