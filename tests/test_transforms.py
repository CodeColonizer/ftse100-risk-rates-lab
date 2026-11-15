"""Offline unit tests on small synthetic data (no downloads needed).

These test the cleaning logic itself, including the real SQL files, so a
change to a rule that breaks it is caught before the pipeline is rerun.
"""
import pandas as pd
import pytest

from ftselab import boe, constituents, db, quality


# --- Constituents ----------------------------------------------------------------

@pytest.mark.parametrize("epic, expected", [
    ("AZN", "AZN.L"),
    ("BT.A", "BT-A.L"),
    ("RR.", "RR.L"),
    (" hsba ", "HSBA.L"),
])
def test_epic_to_yahoo(epic, expected):
    assert constituents.epic_to_yahoo(epic) == expected


def test_epic_to_yahoo_rejects_empty():
    with pytest.raises(ValueError):
        constituents.epic_to_yahoo("  ")


def test_build_snapshot_maps_industry_and_flags_trusts():
    raw = pd.DataFrame({
        "company": ["Barclays", "Scottish Mortgage"],
        "epic": ["BARC", "SMT"],
        "isin": ["GB0031348658", "GB00BLDYK618"],
        "icb_sector": ["Banks", "Closed End Investments"],
    })
    snap = constituents.build_snapshot(raw, "2026-11-15", "http://example")
    assert list(snap.columns) == constituents.SNAPSHOT_COLUMNS
    assert snap.set_index("epic").loc["BARC", "icb_industry"] == "Financials"
    assert snap.set_index("epic").loc["SMT", "is_investment_trust"] == 1
    assert snap.set_index("epic").loc["BARC", "is_investment_trust"] == 0


def test_build_snapshot_rejects_unknown_sector():
    raw = pd.DataFrame({"company": ["X"], "epic": ["X"], "isin": ["GB0"], "icb_sector": ["Made Up"]})
    with pytest.raises(ValueError, match="Made Up"):
        constituents.build_snapshot(raw, "2026-11-15", "http://example")


def test_committed_snapshot_sectors_all_mapped():
    snap = constituents.load_snapshot()
    assert set(snap["icb_sector"]) <= set(constituents.ICB_SECTOR_TO_INDUSTRY)
    assert snap["yahoo_ticker"].str.endswith(".L").all()


# --- Bank of England -------------------------------------------------------------

@pytest.mark.parametrize("old, new, expected", [
    (0.5, 0.75, "hike"), (5.25, 5.0, "cut"), (0.1, 0.1, "hold"),
    (0.1 + 0.2, 0.3, "hold"),  # floating point noise is not a decision
])
def test_classify_decision(old, new, expected):
    assert boe.classify_decision(old, new) == expected


def test_build_decisions_uses_prior_meeting_for_first_old_rate():
    meetings = pd.DataFrame({
        "decision_date": pd.to_datetime(["2009-12-10", "2010-01-07", "2016-08-04", "2020-03-11"]),
        "new_rate_pct": [0.5, 0.5, 0.25, 0.25],
    })
    out = boe.build_decisions(meetings, start_date="2010-01-01")
    assert out["decision_date"].tolist() == ["2010-01-07", "2016-08-04", "2020-03-11"]
    assert out["old_rate_pct"].tolist() == [0.5, 0.5, 0.25]
    assert out["decision"].tolist() == ["hold", "cut", "hold"]
    assert out["change_bp"].tolist() == [0, -25, 0]
    assert out["is_scheduled"].tolist() == [1, 1, 0]  # 11 March 2020 was an emergency meeting


def test_build_decisions_needs_earlier_meeting():
    meetings = pd.DataFrame({"decision_date": pd.to_datetime(["2010-01-07"]), "new_rate_pct": [0.5]})
    with pytest.raises(ValueError):
        boe.build_decisions(meetings, start_date="2010-01-01")


def test_parse_bank_rate_daily(tmp_path):
    f = tmp_path / "iudbedr.csv"
    f.write_text("DATE,IUDBEDR\n10 Nov 2026,4\n09 Nov 2026,3.75\n")
    out = boe.parse_bank_rate_daily(f)
    assert out["date"].tolist() == ["2026-11-09", "2026-11-10"]
    assert out["bank_rate_pct"].tolist() == [3.75, 4.0]


# --- Clean-layer SQL on a synthetic database -----------------------------------------

def _price_rows(ticker, dates, adj, volume=1000):
    return [{"ticker": ticker, "date": d, "open": a, "high": a, "low": a, "close": a,
             "adj_close": a, "volume": volume, "downloaded_at": "2026-11-15T00:00:00Z"}
            for d, a in zip(dates, adj)]


@pytest.fixture
def synthetic_db():
    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
            "2026-01-12", "2026-01-13"]
    rows = _price_rows("^FTSE", days, [100, 101, 102, 103, 104, 105, 106], volume=0)
    # SPK.L: one-day 100x glitch on 7 Jan that reverses on 8 Jan -> removed
    rows += _price_rows("SPK.L", days, [500, 505, 50500, 510, 512, 515, 520])
    # SHF.L: permanent 100x drop from 9 Jan (pence -> pounds switch) -> flagged
    rows += _price_rows("SHF.L", days, [800, 805, 810, 812, 8.1, 8.2, 8.3])
    # BIG.L: genuine 40% fall on 8 Jan -> extreme move flagged, kept;
    # missing 12 Jan; duplicate row for 6 Jan; a Saturday row (dropped)
    rows += _price_rows("BIG.L", ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
                                  "2026-01-09", "2026-01-13"], [200, 202, 204, 122, 123, 124])
    rows += _price_rows("BIG.L", ["2026-01-06"], [999])  # older duplicate
    rows[-1]["downloaded_at"] = "2025-01-01T00:00:00Z"
    rows += _price_rows("BIG.L", ["2026-01-10"], [130])  # Saturday
    # STL.L: zero volume, unchanged close on 9 Jan -> stale flag
    stale = _price_rows("STL.L", days, [50, 51, 52, 53, 53, 54, 55])
    stale[4]["volume"] = 0
    rows += stale
    # BAD.L: flat bar (open = high = low = close) +30% on 7 Jan, back next day -> removed
    rows += _price_rows("BAD.L", days, [100, 101, 131, 102, 103, 104, 105])
    for r in rows[-7:]:
        if r["date"] != "2026-01-07":
            r["high"], r["low"] = r["close"] * 1.01, r["close"] * 0.99
    # SPL.L: unadjusted 10-for-1 split before 7 Jan -> scaled by 0.1
    rows += _price_rows("SPL.L", days, [1000, 1010, 102, 103, 104, 105, 106])
    # LST.L: unusable history before 8 Jan -> dropped and logged
    rows += _price_rows("LST.L", days, [5, 5, 5, 300, 301, 302, 303])
    # USD.L: quoted in US dollars -> converted to pence at GBPUSD
    rows += _price_rows("USD.L", days, [12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5])

    tickers = ["SPK.L", "SHF.L", "BIG.L", "STL.L", "BAD.L", "SPL.L", "LST.L", "USD.L"]
    n = len(tickers)
    cons = pd.DataFrame({
        "epic": [t[:-2] for t in tickers], "yahoo_ticker": tickers,
        "company": [f"Company {t}" for t in tickers], "isin": [f"I{i}" for i in range(n)],
        "icb_sector": ["Banks"] * n, "icb_industry": ["Financials"] * n,
        "is_investment_trust": ["0"] * n, "snapshot_date": ["2026-11-15"] * n,
        "source_url": ["x"] * n,
    })
    corrections = pd.DataFrame({
        "ticker": ["SPL.L", "LST.L"], "action": ["scale_before", "drop_before"],
        "before_date": ["2026-01-07", "2026-01-08"], "factor": [0.1, None],
        "reason": ["split", "pre-listing"], "evidence": ["test", "test"],
    })
    # 1.25 dollars per pound until 9 Jan, then 1.30 (no rate published on 12 Jan)
    fx = pd.DataFrame({"pair": ["GBPUSD=X"] * 3, "date": ["2026-01-05", "2026-01-09", "2026-01-13"],
                       "rate": [1.25, 1.30, 1.30]})
    decisions = pd.DataFrame({
        "decision_date": ["2026-01-08", "2026-01-10"], "old_rate_pct": [3.75, 4.0],
        "new_rate_pct": [4.0, 4.0], "change_bp": [25, 0], "decision": ["hike", "hold"],
        "is_scheduled": [1, 1], "source": ["test", "test"],
    })
    bank_rate = pd.DataFrame({"date": ["2026-01-05", "2026-01-08"], "bank_rate_pct": [3.75, 4.0]})
    info = pd.DataFrame({"ticker": ["SPK.L", "USD.L"], "currency": ["GBp", "USD"],
                         "exchange": ["LSE", "LSE"]})

    conn = db.connect(":memory:")
    db.load_raw(conn, {"prices": pd.DataFrame(rows), "ticker_info": info, "fx": fx,
                       "price_corrections": corrections, "constituents": cons,
                       "boe_decisions": decisions, "bank_rate_daily": bank_rate})
    db.build_clean(conn)
    yield conn
    conn.close()


def test_calendar_comes_from_index(synthetic_db):
    cal = db.query("SELECT date FROM clean_trading_calendar", synthetic_db)
    assert len(cal) == 7 and "2026-01-10" not in cal["date"].tolist()


def test_unit_spike_removed_and_logged(synthetic_db):
    spk = db.query("SELECT date FROM clean_prices WHERE ticker = 'SPK.L'", synthetic_db)
    assert "2026-01-07" not in spk["date"].tolist()
    exc = db.query("SELECT ticker, date FROM clean_price_exclusions WHERE ticker = 'SPK.L'",
                   synthetic_db)
    assert exc.values.tolist() == [["SPK.L", "2026-01-07"]]
    # the reversal day is not mistaken for a unit shift or extreme move
    flags = db.query("SELECT is_unit_shift, is_extreme_move FROM clean_prices "
                     "WHERE ticker = 'SPK.L' AND date = '2026-01-08'", synthetic_db)
    assert flags.iloc[0].tolist() == [0, 0]


def test_unit_shift_flagged_not_removed(synthetic_db):
    shf = db.query("SELECT date, is_unit_shift FROM clean_prices WHERE ticker = 'SHF.L'", synthetic_db)
    assert len(shf) == 7
    assert shf.loc[shf["is_unit_shift"] == 1, "date"].tolist() == ["2026-01-09"]


def test_extreme_move_flagged_duplicate_and_weekend_handled(synthetic_db):
    big = db.query("SELECT date, adj_close, is_extreme_move FROM clean_prices "
                   "WHERE ticker = 'BIG.L' ORDER BY date", synthetic_db)
    assert big.loc[big["date"] == "2026-01-06", "adj_close"].tolist() == [202]  # latest download wins
    assert "2026-01-10" not in big["date"].tolist()                            # weekend dropped
    assert big.loc[big["is_extreme_move"] == 1, "date"].tolist() == ["2026-01-08"]


def test_missing_days_counted_not_filled(synthetic_db):
    c = db.query("SELECT ticker, n_price_days, n_missing_days FROM clean_constituents "
                 "WHERE ticker = 'BIG.L'", synthetic_db)
    assert c.iloc[0].tolist() == ["BIG.L", 6, 1]


def test_stale_day_flagged(synthetic_db):
    stl = db.query("SELECT date FROM clean_prices WHERE ticker = 'STL.L' AND is_stale = 1", synthetic_db)
    assert stl["date"].tolist() == ["2026-01-09"]


def test_flat_bar_bad_print_removed(synthetic_db):
    bad = db.query("SELECT date FROM clean_prices WHERE ticker = 'BAD.L'", synthetic_db)
    assert "2026-01-07" not in bad["date"].tolist() and len(bad) == 6
    reason = db.query("SELECT reason FROM clean_price_exclusions WHERE ticker = 'BAD.L'", synthetic_db)
    assert reason["reason"].str.startswith("flat-bar").all() and len(reason) == 1


def test_split_correction_scales_earlier_prices(synthetic_db):
    spl = db.query("SELECT date, adj_close, was_corrected, is_extreme_move FROM clean_prices "
                   "WHERE ticker = 'SPL.L' ORDER BY date", synthetic_db)
    assert spl["adj_close"].round(6).tolist() == [100, 101, 102, 103, 104, 105, 106]
    assert spl["was_corrected"].tolist() == [1, 1, 0, 0, 0, 0, 0]
    assert spl["is_extreme_move"].sum() == 0


def test_drop_before_removes_and_logs_history(synthetic_db):
    lst = db.query("SELECT date FROM clean_prices WHERE ticker = 'LST.L'", synthetic_db)
    assert lst["date"].min() == "2026-01-08"
    logged = db.query("SELECT COUNT(*) n FROM clean_price_exclusions WHERE ticker = 'LST.L' "
                      "AND reason LIKE 'before usable history%'", synthetic_db)
    assert logged["n"].iloc[0] == 3


def test_usd_line_converted_to_pence(synthetic_db):
    usd = db.query("SELECT date, quote_currency, adj_close FROM clean_prices "
                   "WHERE ticker = 'USD.L' ORDER BY date", synthetic_db)
    assert (usd["quote_currency"] == "USD").all()
    # $12.50 at 1.25 $/GBP = 1000p; at 1.30 = 961.5p; 12 Jan uses the 9 Jan rate
    expected = [1000.0] * 4 + [12.5 / 1.30 * 100] * 3
    assert usd["adj_close"].round(4).tolist() == [round(x, 4) for x in expected]


def test_boe_alignment(synthetic_db):
    d = db.query("SELECT decision_date, event_date, iudbedr_rate_pct FROM clean_boe_decisions",
                 synthetic_db)
    # a Saturday decision maps to the following Monday
    assert d.values.tolist() == [["2026-01-08", "2026-01-08", 4.0], ["2026-01-10", "2026-01-12", 4.0]]
    br = db.query("SELECT bank_rate_pct FROM clean_bank_rate_daily ORDER BY date", synthetic_db)
    assert br["bank_rate_pct"].tolist() == [3.75, 3.75, 3.75, 4.0, 4.0, 4.0, 4.0]


def test_quality_checks_catch_planted_problems(synthetic_db):
    report = quality.run_checks(synthetic_db).set_index("check")
    assert report.loc["prices_no_unit_shifts", "status"] == "fail"
    assert report.loc["prices_extreme_moves_reported", "status"] == "review"
    assert report.loc["prices_unique_ticker_date", "status"] == "pass"
    assert report.loc["boe_matches_official_series", "status"] == "pass"
    assert report.loc["prices_rows_accounted_for", "status"] == "pass"
    assert report.loc["prices_corrections_applied", "status"] == "pass"
    assert report.loc["prices_fx_available", "status"] == "pass"


def test_market_wide_stale_day_removed(monkeypatch):
    """When several stocks repeat yesterday's close with zero volume on the same
    day, the rows are removed (the source filled a gap); a lone stale stock stays."""
    monkeypatch.setitem(db.SQL_TOKENS, "STALE_DAY_MIN_STOCKS", 2)
    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    rows = _price_rows("^FTSE", days, [100, 101, 99, 102], volume=0)
    for t in ["AAA.L", "BBB.L"]:
        r = _price_rows(t, days, [10, 11, 11, 12])
        r[2]["volume"] = 0          # 7 Jan: unchanged close, zero volume
        rows += r
    lone = _price_rows("CCC.L", days, [20, 21, 22, 22])
    lone[3]["volume"] = 0           # 8 Jan: only this stock is stale
    rows += lone
    cons = pd.DataFrame({"epic": ["AAA", "BBB", "CCC"], "yahoo_ticker": ["AAA.L", "BBB.L", "CCC.L"],
                         "company": list("ABC"), "isin": ["1", "2", "3"], "icb_sector": ["Banks"] * 3,
                         "icb_industry": ["Financials"] * 3, "is_investment_trust": ["0"] * 3,
                         "snapshot_date": ["x"] * 3, "source_url": ["x"] * 3})
    conn = db.connect(":memory:")
    db.load_raw(conn, {
        "prices": pd.DataFrame(rows),
        "ticker_info": pd.DataFrame({"ticker": ["AAA.L"], "currency": ["GBp"], "exchange": ["LSE"]}),
        "fx": pd.DataFrame({"pair": ["GBPUSD=X"], "date": ["2026-01-05"], "rate": [1.3]}),
        "price_corrections": pd.DataFrame(columns=["ticker", "action", "before_date", "factor",
                                                   "reason", "evidence"]),
        "constituents": cons,
        "boe_decisions": pd.DataFrame({"decision_date": ["2026-01-06"], "old_rate_pct": [4.0],
                                       "new_rate_pct": [4.0], "change_bp": [0], "decision": ["hold"],
                                       "is_scheduled": [1], "source": ["t"]}),
        "bank_rate_daily": pd.DataFrame({"date": ["2026-01-05"], "bank_rate_pct": [4.0]}),
    })
    db.build_clean(conn)
    kept = db.query("SELECT ticker FROM clean_prices WHERE date = '2026-01-07' "
                    "AND ticker <> '^FTSE'", conn)
    assert kept["ticker"].tolist() == ["CCC.L"]  # CCC traded normally that day
    logged = db.query("SELECT ticker FROM clean_price_exclusions WHERE reason LIKE 'carried-forward%'", conn)
    assert sorted(logged["ticker"]) == ["AAA.L", "BBB.L"]
    lone_kept = db.query("SELECT is_stale FROM clean_prices WHERE ticker = 'CCC.L' AND date = '2026-01-08'", conn)
    assert lone_kept["is_stale"].tolist() == [1]
    conn.close()


def test_render_sql_rejects_unknown_token():
    with pytest.raises(ValueError):
        db.render_sql("SELECT {{NOT_A_TOKEN}}")
