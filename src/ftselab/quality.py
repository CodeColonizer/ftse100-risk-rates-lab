"""Automated data quality checks on the built database.

Each check is a SQL query that returns the rows that FAIL it (zero rows =
pass). 'error' checks must pass for the pipeline to succeed; 'warning' checks
are reported for review. The same list drives the pytest suite
(tests/test_data_quality.py) and the CSV report, so they never disagree.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from . import config
from .constituents import ICB_INDUSTRIES


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # 'error' or 'warning'
    description: str
    sql: str


def _in_list(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


CHECKS: list[Check] = [
    # --- Prices -------------------------------------------------------------
    Check("prices_unique_ticker_date", "error",
          "One clean price per ticker and day",
          "SELECT ticker, date, COUNT(*) n FROM clean_prices GROUP BY ticker, date HAVING n > 1"),
    Check("prices_no_null_keys", "error",
          "Ticker, date and adjusted close are never missing",
          "SELECT * FROM clean_prices WHERE ticker IS NULL OR date IS NULL OR adj_close IS NULL"),
    Check("prices_positive", "error",
          "Prices are strictly positive",
          "SELECT * FROM clean_prices WHERE adj_close <= 0 OR close <= 0"),
    Check("prices_high_low_consistent", "warning",
          "Daily low is not above the daily high",
          "SELECT * FROM clean_prices WHERE low > high"),
    Check("prices_no_weekends", "error",
          "No prices on Saturdays or Sundays",
          "SELECT * FROM clean_prices WHERE CAST(strftime('%w', date) AS INTEGER) IN (0, 6)"),
    Check("prices_no_future_dates", "error",
          "No prices dated after today",
          "SELECT * FROM clean_prices WHERE date > date('now')"),
    Check("prices_start_on_or_after_start_date", "error",
          f"No prices before the analysis start ({config.START_DATE})",
          f"SELECT * FROM clean_prices WHERE date < '{config.START_DATE}'"),
    Check("prices_on_calendar", "error",
          "Every price date is an index trading day",
          "SELECT p.* FROM clean_prices p LEFT JOIN clean_trading_calendar c ON c.date = p.date "
          "WHERE c.date IS NULL"),
    Check("prices_no_unit_shifts", "error",
          "No unexplained ~100x price level changes (pence/pound unit errors)",
          "SELECT ticker, date, adj_close FROM clean_prices WHERE is_unit_shift = 1"),
    Check("prices_extreme_moves_reported", "warning",
          f"One-day moves above {config.EXTREME_MOVE:.0%} (kept; listed for review)",
          "SELECT p.ticker, p.date, p.adj_close FROM clean_prices p WHERE is_extreme_move = 1"),
    Check("prices_no_market_wide_stale_days", "error",
          f"No day with {config.STALE_DAY_MIN_STOCKS}+ stocks carrying yesterday's price forward",
          "SELECT date, COUNT(*) n FROM clean_prices WHERE is_stale = 1 GROUP BY date "
          f"HAVING n >= {config.STALE_DAY_MIN_STOCKS}"),
    Check("prices_stale_days_reported", "warning",
          "Zero-volume days with an unchanged close (kept; listed for review)",
          "SELECT ticker, date FROM clean_prices WHERE is_stale = 1"),
    Check("prices_rows_accounted_for", "error",
          "Every raw row on a trading day is either in the clean layer or logged as excluded",
          "SELECT r.ticker, r.n_raw, COALESCE(c.n, 0) n_clean, COALESCE(x.n, 0) n_excluded FROM "
          "(SELECT ticker, COUNT(DISTINCT date) n_raw FROM raw_prices "
          " WHERE date IN (SELECT date FROM clean_trading_calendar) "
          " AND adj_close > 0 AND close > 0 GROUP BY ticker) r "
          "LEFT JOIN (SELECT ticker, COUNT(*) n FROM clean_prices GROUP BY ticker) c ON c.ticker = r.ticker "
          "LEFT JOIN (SELECT ticker, COUNT(*) n FROM clean_price_exclusions GROUP BY ticker) x "
          "  ON x.ticker = r.ticker "
          "WHERE r.n_raw <> COALESCE(c.n, 0) + COALESCE(x.n, 0)"),
    Check("prices_fx_available", "error",
          "Every USD/EUR-quoted price has an exchange rate from within the previous 5 days",
          "SELECT p.ticker, p.date FROM clean_prices p WHERE p.quote_currency IN ('USD', 'EUR') "
          "AND NOT EXISTS (SELECT 1 FROM raw_fx f WHERE f.pair = 'GBP' || p.quote_currency || '=X' "
          "AND f.date BETWEEN date(p.date, '-5 days') AND p.date)"),
    Check("prices_corrections_applied", "error",
          "Every documented correction in price_corrections.csv changed at least one row",
          "SELECT k.ticker, k.action FROM raw_price_corrections k WHERE NOT EXISTS ("
          " SELECT 1 FROM clean_prices p WHERE p.ticker = k.ticker AND p.was_corrected = 1) "
          "AND NOT EXISTS (SELECT 1 FROM clean_price_exclusions x WHERE x.ticker = k.ticker "
          " AND x.reason LIKE 'before usable history%')"),
    Check("prices_exclusions_reported", "warning",
          "Rows removed from the clean layer (listed with reasons in clean_price_exclusions)",
          "SELECT ticker, date, reason FROM clean_price_exclusions"),
    Check("index_covers_start", "error",
          "FTSE 100 index history starts in the first week of the window",
          f"SELECT MIN(date) first_date FROM clean_prices WHERE ticker = '{config.INDEX_TICKER}' "
          f"HAVING first_date IS NULL OR first_date > date('{config.START_DATE}', '+7 days')"),
    Check("index_is_recent", "warning",
          "FTSE 100 index data is no more than 7 days old",
          f"SELECT MAX(date) last_date FROM clean_prices WHERE ticker = '{config.INDEX_TICKER}' "
          "HAVING last_date < date('now', '-7 days')"),
    # --- Constituents ----------------------------------------------------------
    Check("constituents_count", "error",
          f"Between {config.MIN_CONSTITUENTS} and {config.MAX_CONSTITUENTS} constituents",
          "SELECT COUNT(*) n FROM clean_constituents "
          f"HAVING n NOT BETWEEN {config.MIN_CONSTITUENTS} AND {config.MAX_CONSTITUENTS}"),
    Check("constituents_unique", "error",
          "Each ticker and ISIN appears once",
          "SELECT ticker FROM clean_constituents GROUP BY ticker HAVING COUNT(*) > 1 "
          "UNION ALL SELECT isin FROM clean_constituents GROUP BY isin HAVING COUNT(*) > 1"),
    Check("constituents_have_sector", "error",
          "Every constituent has a valid ICB sector and industry",
          "SELECT * FROM clean_constituents WHERE icb_sector IS NULL OR icb_sector = '' "
          f"OR icb_industry NOT IN ({_in_list(ICB_INDUSTRIES)})"),
    Check("constituents_have_prices", "error",
          "Every constituent has price data",
          "SELECT ticker FROM clean_constituents WHERE n_price_days = 0"),
    Check("constituents_prices_recent", "error",
          "Every constituent's latest price is within 7 days of the index's latest date",
          "SELECT ticker, last_price_date FROM clean_constituents WHERE last_price_date < "
          f"(SELECT date(MAX(date), '-7 days') FROM clean_prices WHERE ticker = '{config.INDEX_TICKER}')"),
    Check("constituents_missing_days", "error",
          f"No stock misses more than {config.MAX_MISSING_SHARE:.0%} of trading days after it starts",
          "SELECT ticker, n_missing_days, n_price_days FROM clean_constituents "
          f"WHERE n_missing_days > {config.MAX_MISSING_SHARE} * (n_price_days + n_missing_days)"),
    Check("constituents_late_starters_reported", "warning",
          "Stocks whose price history starts after January 2010 (listed later; reported)",
          "SELECT ticker, company, first_price_date FROM clean_constituents "
          f"WHERE first_price_date > date('{config.START_DATE}', '+31 days') ORDER BY first_price_date"),
    # --- Bank of England ----------------------------------------------------------
    Check("boe_dates_unique", "error",
          "One decision per date",
          "SELECT decision_date FROM clean_boe_decisions GROUP BY decision_date HAVING COUNT(*) > 1"),
    Check("boe_decision_matches_rates", "error",
          "Decision label (hike/cut/hold) agrees with old and new rate",
          "SELECT * FROM clean_boe_decisions WHERE "
          "(decision = 'hike' AND new_rate_pct <= old_rate_pct) OR "
          "(decision = 'cut'  AND new_rate_pct >= old_rate_pct) OR "
          "(decision = 'hold' AND new_rate_pct <> old_rate_pct) OR "
          "decision NOT IN ('hike', 'cut', 'hold')"),
    Check("boe_chain_consistent", "error",
          "Each decision's old rate equals the previous decision's new rate",
          "SELECT * FROM (SELECT decision_date, old_rate_pct, "
          "LAG(new_rate_pct) OVER (ORDER BY decision_date) prev_new FROM clean_boe_decisions) "
          "WHERE prev_new IS NOT NULL AND ABS(old_rate_pct - prev_new) > 1e-9"),
    Check("boe_matches_official_series", "error",
          "New rate equals the official daily Bank Rate (IUDBEDR) on the decision date",
          "SELECT * FROM clean_boe_decisions WHERE iudbedr_rate_pct IS NULL "
          "OR ABS(new_rate_pct - iudbedr_rate_pct) > 1e-9"),
    Check("boe_series_changes_are_decisions", "error",
          "Every change in the daily Bank Rate series falls on an MPC decision date",
          "SELECT date, bank_rate_pct FROM (SELECT date, bank_rate_pct, "
          "LAG(bank_rate_pct) OVER (ORDER BY date) prev FROM raw_bank_rate_daily) "
          f"WHERE date >= '{config.START_DATE}' AND prev IS NOT NULL AND bank_rate_pct <> prev "
          "AND date NOT IN (SELECT decision_date FROM clean_boe_decisions)"),
    Check("boe_rates_in_range", "error",
          "Bank Rate between 0% and 6% throughout",
          "SELECT * FROM clean_boe_decisions WHERE new_rate_pct < 0 OR new_rate_pct > 6 "
          "OR old_rate_pct < 0 OR old_rate_pct > 6"),
    Check("boe_event_on_trading_day", "error",
          "Every decision maps to a trading day within 3 days (except the latest, if not yet traded)",
          "SELECT * FROM clean_boe_decisions WHERE (event_date IS NULL AND decision_date < "
          f"(SELECT MAX(date) FROM clean_trading_calendar)) OR julianday(event_date) - julianday(decision_date) > 3"),
    Check("bank_rate_daily_complete", "error",
          "Bank Rate known on every trading day",
          "SELECT * FROM clean_bank_rate_daily WHERE bank_rate_pct IS NULL"),
]


def run_checks(conn: sqlite3.Connection, checks: list[Check] = CHECKS) -> pd.DataFrame:
    """Run all checks and return one row per check with status and examples."""
    rows = []
    for c in checks:
        failing = pd.read_sql_query(c.sql, conn)
        n = len(failing)
        status = "pass" if n == 0 else ("fail" if c.severity == "error" else "review")
        example = "" if n == 0 else "; ".join(
            ", ".join(str(v) for v in r) for r in failing.head(5).itertuples(index=False))
        rows.append({"check": c.name, "severity": c.severity, "status": status,
                     "rows_flagged": n, "description": c.description, "examples": example})
    return pd.DataFrame(rows)


def write_report(report: pd.DataFrame) -> None:
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(config.OUTPUTS_DIR / "data_quality_report.csv", index=False)
