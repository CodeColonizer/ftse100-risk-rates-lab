"""Export small, app-ready tables for the Streamlit app (app/data/).

The app never touches raw prices. It reads summary tables only: risk metrics,
sector-level growth indices sampled weekly, correlations, stress-period
returns, event-study results and data quality status. This keeps the
deployed data small and avoids publishing raw price data.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

APP_DATA_DIR = config.ROOT / "app" / "data"
INDEX = config.INDEX_TICKER


def _q(conn, sql):
    return pd.read_sql_query(sql, conn)


def _weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the last trading day of each week (plus the very last day)."""
    d = pd.to_datetime(df["date"])
    week = d.dt.strftime("%G-%V")
    last = df.groupby(week)["date"].transform("max")
    out = df[(df["date"] == last) | (df["date"] == df["date"].max())]
    return out.drop_duplicates()


def growth_indices(conn) -> pd.DataFrame:
    """Growth of 100 for each sector, the equal-weighted market and the FTSE 100."""
    sec = _q(conn, "SELECT date, sector, daily_return FROM mart_sector_daily_returns")
    idx = _q(conn, f"SELECT date, daily_return FROM mart_daily_returns WHERE ticker = '{INDEX}'")
    idx["sector"] = "FTSE 100 index (price only)"
    both = pd.concat([sec, idx], ignore_index=True)
    wide = both.pivot(index="date", columns="sector", values="daily_return").sort_index()
    growth = 100 * (1 + wide.fillna(0)).cumprod()
    # rebase every series to 100 on the first day the FTSE 100 has a return
    growth = growth / growth.iloc[0] * 100
    long = growth.reset_index().melt(id_vars="date", var_name="series", value_name="growth_of_100")
    return _weekly(long.sort_values(["series", "date"])).reset_index(drop=True)


def export(conn: sqlite3.Connection, out_dir: Path = APP_DATA_DIR) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}

    tables["sector_risk"] = _q(conn, "SELECT * FROM mart_sector_risk")
    tables["stock_risk"] = _q(
        conn, "SELECT ticker, company, icb_industry, is_investment_trust, years, ann_return, "
              "ann_volatility, sharpe, beta, corr_with_index, max_drawdown, peak_date, trough_date, "
              "recovery_date, worst_day_return, worst_day_date, short_history FROM mart_stock_risk")
    tables["sector_growth"] = growth_indices(conn)
    tables["sector_correlation"] = _q(conn, "SELECT * FROM mart_sector_correlation")
    tables["rolling_corr"] = _weekly(
        _q(conn, "SELECT * FROM mart_rolling_sector_corr ORDER BY sector, date"))
    tables["stress_periods"] = _q(
        conn, "SELECT period, label, base_date, end_date, kind, name, window_return, vs_index, "
              "max_drawdown_in_window, value FROM mart_stress_periods")
    tables["stress_definitions"] = _q(conn, "SELECT * FROM mart_stress_period_definitions")
    tables["event_results"] = _q(
        conn, "SELECT kind, series, \"group\", group_description, window, n_events, mean, median, "
              "share_positive, ci95_low, ci95_high, p_t, p_placebo, p_placebo_mean, placebo_centre, "
              "q_fdr_placebo FROM mart_event_results WHERE kind <> 'stock'")
    tables["event_stock_results"] = _q(
        conn, "SELECT series AS ticker, \"group\", window, n_events, mean, p_placebo, q_fdr_placebo "
              "FROM mart_event_results WHERE kind = 'stock' AND window = 'm1_p1'")
    tables["event_volatility"] = _q(conn, "SELECT * FROM mart_event_volatility")
    tables["event_path"] = _q(conn, "SELECT * FROM mart_event_path")
    tables["boe_decisions"] = _q(
        conn, "SELECT d.decision_date, d.old_rate_pct, d.new_rate_pct, d.change_bp, d.decision, "
              "d.is_scheduled, COALESCE(e.included, 0) AS in_event_study "
              "FROM clean_boe_decisions d LEFT JOIN mart_event_list e ON e.decision_date = d.decision_date "
              "ORDER BY d.decision_date")
    quality = pd.read_csv(config.OUTPUTS_DIR / "data_quality_report.csv")
    tables["quality_report"] = quality

    written = []
    for name, df in tables.items():
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False, float_format="%.6g")
        written.append(str(path))

    last = _q(conn, f"SELECT MAX(date) d FROM clean_prices WHERE ticker = '{INDEX}'")["d"].iloc[0]
    dec = tables["boe_decisions"].iloc[-1]
    meta = {
        "data_through": last,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "n_stocks": int(len(tables["stock_risk"]) - 1),
        "n_decisions_total": int(len(tables["boe_decisions"])),
        "n_decisions_analysed": int(tables["boe_decisions"]["in_event_study"].sum()),
        "bank_rate_now_pct": float(dec["new_rate_pct"]),
        "last_decision": {"date": dec["decision_date"], "decision": dec["decision"],
                          "new_rate_pct": float(dec["new_rate_pct"])},
        "quality": {
            "checks": int(len(quality)),
            "passed": int((quality["status"] == "pass").sum()),
            "for_review": int((quality["status"] == "review").sum()),
            "failed": int((quality["status"] == "fail").sum()),
        },
        "start_date": config.START_DATE,
        "fdr_level": config.FDR_LEVEL,
        "placebo_draws": config.PLACEBO_DRAWS,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    written.append(str(out_dir / "meta.json"))
    return written


def total_size_kb(out_dir: Path = APP_DATA_DIR) -> float:
    return float(np.sum([p.stat().st_size for p in out_dir.glob("*")]) / 1024)
