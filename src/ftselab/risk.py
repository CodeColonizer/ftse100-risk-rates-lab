"""Phase 2 risk analytics: returns, volatility, drawdown, beta, Sharpe,
sector correlations and stress periods.

Pure functions (top half) take pandas objects and are unit tested on
synthetic data. build() (bottom half) reads the clean layer, computes
everything and writes `mart_` tables plus small CSV summaries.

Conventions
  * Simple daily returns from the adjusted close (includes dividends).
  * A return needs prices on two consecutive trading days; gaps stay gaps.
  * Annualised volatility = daily standard deviation x sqrt(252).
  * Annualised return = compound growth rate (CAGR) over the returns used.
  * Sharpe = mean daily excess return / its standard deviation x sqrt(252),
    where the daily risk-free return comes from Bank Rate on that day.
  * Sector portfolios are equal-weighted, rebalanced daily, across the
    members with a return that day.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from . import config

INDEX = config.INDEX_TICKER
ANN = config.TRADING_DAYS


# ----------------------------------------------------------------------------------
# Pure functions
# ----------------------------------------------------------------------------------

def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple returns from a date x ticker price frame on the full trading calendar.

    Missing prices are not filled, so a return is NaN unless the stock has a
    price both on that day and on the previous trading day.
    """
    return prices.pct_change(fill_method=None)


def daily_risk_free(bank_rate_pct: pd.Series, periods: int = ANN) -> pd.Series:
    """Convert an annual Bank Rate in % into a daily compounded return."""
    return (1 + bank_rate_pct / 100) ** (1 / periods) - 1


def annualised_volatility(returns: pd.Series, periods: int = ANN) -> float:
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(periods)) if len(r) > 1 else np.nan


def annualised_return(returns: pd.Series, periods: int = ANN) -> float:
    """Compound annual growth rate implied by the available daily returns."""
    r = returns.dropna()
    if r.empty:
        return np.nan
    growth = float((1 + r).prod())
    return growth ** (periods / len(r)) - 1


def sharpe_ratio(returns: pd.Series, rf_daily: pd.Series, periods: int = ANN) -> float:
    excess = (returns - rf_daily.reindex(returns.index)).dropna()
    sd = excess.std(ddof=1)
    if len(excess) < 2 or sd == 0 or np.isnan(sd):
        return np.nan
    return float(excess.mean() / sd * np.sqrt(periods))


def max_drawdown(prices: pd.Series) -> dict:
    """Largest peak-to-trough fall in a price (or wealth) series.

    Returns the drawdown (negative), peak and trough dates, the recovery date
    (first date back at the old peak) or None if not yet recovered, and the
    number of trading days from peak to recovery.
    """
    p = prices.dropna()
    if p.empty:
        return {"max_drawdown": np.nan, "peak_date": None, "trough_date": None,
                "recovery_date": None, "days_to_recover": None}
    running_peak = p.cummax()
    dd = p / running_peak - 1
    trough = dd.idxmin()
    peak = p.loc[:trough].idxmax()
    after = p.loc[trough:]
    recovered = after[after >= p.loc[peak]]
    recovery = recovered.index[0] if not recovered.empty else None
    days = int(p.index.get_loc(recovery) - p.index.get_loc(peak)) if recovery is not None else None
    return {"max_drawdown": float(dd.min()), "peak_date": peak, "trough_date": trough,
            "recovery_date": recovery, "days_to_recover": days}


def beta(returns: pd.Series, market: pd.Series) -> float:
    """OLS beta: covariance with the market / market variance, on shared days."""
    both = pd.concat([returns, market], axis=1, join="inner").dropna()
    if len(both) < 2:
        return np.nan
    var = both.iloc[:, 1].var(ddof=1)
    return float(both.iloc[:, 0].cov(both.iloc[:, 1]) / var) if var > 0 else np.nan


def wealth_index(returns: pd.Series) -> pd.Series:
    """Growth of 1 from compounding returns; days with no return count as 0%."""
    return (1 + returns.fillna(0)).cumprod()


def equal_weight_portfolio(returns: pd.DataFrame) -> pd.Series:
    """Daily rebalanced equal-weight return across the columns available each day."""
    return returns.mean(axis=1, skipna=True)


def window_return(returns: pd.Series, base_date: str, end_date: str) -> float:
    """Compound return from the close on base_date to the close on end_date."""
    r = returns.loc[(returns.index > base_date) & (returns.index <= end_date)].dropna()
    return float((1 + r).prod() - 1) if not r.empty else np.nan


def average_pairwise_correlation(returns: pd.DataFrame) -> float:
    """Mean of the off-diagonal entries of the correlation matrix."""
    corr = returns.corr(min_periods=10).to_numpy()
    mask = ~np.eye(len(corr), dtype=bool)
    vals = corr[mask]
    vals = vals[~np.isnan(vals)]
    return float(vals.mean()) if len(vals) else np.nan


def risk_summary(returns: pd.Series, prices: pd.Series, market: pd.Series,
                 rf_daily: pd.Series) -> dict:
    """All headline metrics for one return series."""
    r = returns.dropna()
    dd = max_drawdown(prices)
    worst = r.idxmin() if not r.empty else None
    return {
        "first_date": r.index.min() if not r.empty else None,
        "last_date": r.index.max() if not r.empty else None,
        "n_returns": int(len(r)),
        "years": round(len(r) / ANN, 2),
        "ann_return": annualised_return(r),
        "ann_volatility": annualised_volatility(r),
        "sharpe": sharpe_ratio(r, rf_daily),
        "beta": beta(r, market),
        "corr_with_index": float(pd.concat([r, market], axis=1, join="inner").corr().iloc[0, 1])
        if len(r) > 2 else np.nan,
        "worst_day_return": float(r.min()) if not r.empty else np.nan,
        "worst_day_date": worst,
        **dd,
    }


# ----------------------------------------------------------------------------------
# Loading from the clean layer
# ----------------------------------------------------------------------------------

def total_return_index(returns: pd.DataFrame, listed: pd.DataFrame) -> pd.DataFrame:
    """Growth of 1 from compounding total returns, only where the stock has a price.

    Used for drawdowns. A day without a return (a gap) counts as 0% so the
    index carries on, but days before listing stay empty."""
    return (1 + returns.fillna(0)).cumprod().where(listed)


def load_inputs(conn: sqlite3.Connection, exclude_flagged: bool = False):
    """Total-return index and daily total returns (date x ticker on the full
    calendar), members and the daily risk-free return.

    Returns come from clean_total_returns: close plus dividends, built in
    sql/clean/05_total_return.sql (Yahoo's adjusted close is not used for
    London stocks because it barely reflects dividends)."""
    calendar = pd.read_sql_query("SELECT date FROM clean_trading_calendar ORDER BY date", conn)["date"]
    tr = pd.read_sql_query(
        "SELECT t.ticker, t.date, t.total_return, p.is_extreme_move "
        "FROM clean_total_returns t JOIN clean_prices p ON p.ticker = t.ticker AND p.date = t.date",
        conn)
    returns = tr.pivot(index="date", columns="ticker", values="total_return").reindex(calendar)
    flags = tr.pivot(index="date", columns="ticker", values="is_extreme_move").reindex(calendar)
    listed = tr.pivot(index="date", columns="ticker", values="is_extreme_move").reindex(calendar).notna()
    members = pd.read_sql_query(
        "SELECT ticker, company, icb_industry, is_investment_trust, first_price_date "
        "FROM clean_constituents", conn)
    rate = pd.read_sql_query("SELECT date, bank_rate_pct FROM clean_bank_rate_daily", conn)
    rf = daily_risk_free(rate.set_index("date")["bank_rate_pct"]).reindex(calendar)
    if exclude_flagged:
        returns = returns.mask(flags.fillna(0).astype(bool))
    prices = total_return_index(returns, listed)
    return prices, returns, members, rf


def sector_returns(returns: pd.DataFrame, members: pd.DataFrame,
                   tickers: list[str] | None = None) -> pd.DataFrame:
    """Equal-weight daily return per ICB industry (optionally a subset of stocks)."""
    m = members if tickers is None else members[members["ticker"].isin(tickers)]
    out = {}
    for industry, grp in m.groupby("icb_industry"):
        out[industry] = equal_weight_portfolio(returns[grp["ticker"]])
    out = pd.DataFrame(out)
    # a sector with no member returns on a day has no return that day
    counts = pd.DataFrame({ind: returns[g["ticker"]].notna().sum(axis=1)
                           for ind, g in m.groupby("icb_industry")})
    return out.where(counts > 0)


# ----------------------------------------------------------------------------------
# Build everything
# ----------------------------------------------------------------------------------

def _stock_table(prices, returns, members, rf) -> pd.DataFrame:
    market = returns[INDEX]
    rows = []
    for t in list(members["ticker"]) + [INDEX]:
        s = risk_summary(returns[t], prices[t], market, rf)
        rows.append({"ticker": t, **s})
    df = pd.DataFrame(rows).merge(members, on="ticker", how="left")
    df.loc[df["ticker"] == INDEX, ["company", "icb_industry"]] = ["FTSE 100 index (price)", "Index"]
    df["short_history"] = (df["years"] < config.MIN_HISTORY_YEARS).astype(int)
    return df


def _sector_table(sectors: pd.DataFrame, members: pd.DataFrame, market, rf) -> pd.DataFrame:
    rows = []
    for col in sectors.columns:
        r = sectors[col]
        s = risk_summary(r, wealth_index(r), market, rf)
        n_now = int((members["icb_industry"] == col).sum()) if col in set(members["icb_industry"]) else None
        rows.append({"sector": col, "n_stocks_today": n_now, **s})
    return pd.DataFrame(rows)


def _correlations(sectors: pd.DataFrame, market: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    corr = sectors.corr()
    long = corr.stack().dropna().rename("correlation").reset_index()
    long.columns = ["sector_a", "sector_b", "correlation"]
    summary = pd.DataFrame({
        "sector": corr.columns,
        "avg_corr_other_sectors": [corr.loc[c].drop(c).mean() for c in corr.columns],
        "corr_with_index": [sectors[c].corr(market) for c in corr.columns],
    })
    return long, summary


def _rolling_correlations(sectors: pd.DataFrame, market: pd.Series) -> pd.DataFrame:
    roll = sectors.rolling(config.ROLLING_WINDOW, min_periods=config.ROLLING_MIN_PERIODS).corr(market)
    long = roll.stack().dropna().rename("corr_with_index").reset_index()
    long.columns = ["date", "sector", "corr_with_index"]
    return long


def _stress_table(sectors, returns, members, market) -> pd.DataFrame:
    rows = []
    # pairwise correlation is measured across the 11 industries only
    industries = sectors.drop(columns=["All stocks (equal weight)"], errors="ignore")
    series = {**{c: ("sector", sectors[c]) for c in sectors.columns},
              INDEX: ("index", market)}
    series.update({t: ("stock", returns[t]) for t in members["ticker"]})
    for p in config.STRESS_PERIODS:
        b, e = p["base_date"], p["end_date"]
        in_win = (sectors.index > b) & (sectors.index <= e)
        idx_ret = window_return(market, b, e)
        for name, (kind, r) in series.items():
            rw = r[in_win]
            if rw.notna().sum() < max(3, 0.8 * in_win.sum()):
                continue  # not trading (or barely) through the window
            dd = max_drawdown(pd.concat([pd.Series([1.0], index=[b]), wealth_index(rw)]))
            ret = window_return(r, b, e)
            rows.append({
                "period": p["period"], "label": p["label"], "base_date": b, "end_date": e,
                "kind": kind, "name": name, "window_return": ret,
                "vs_index": ret - idx_ret, "max_drawdown_in_window": dd["max_drawdown"],
                "ann_volatility_in_window": annualised_volatility(rw),
            })
        rows.append({"period": p["period"], "label": p["label"], "base_date": b, "end_date": e,
                     "kind": "summary", "name": "avg_pairwise_sector_corr",
                     "window_return": np.nan, "vs_index": np.nan, "max_drawdown_in_window": np.nan,
                     "ann_volatility_in_window": np.nan,
                     "value": average_pairwise_correlation(industries[in_win])})
    out = pd.DataFrame(rows)
    full = average_pairwise_correlation(industries)
    out = pd.concat([out, pd.DataFrame([{"period": "full_period", "label": "Full period",
                                         "kind": "summary", "name": "avg_pairwise_sector_corr",
                                         "value": full}])], ignore_index=True)
    return out


def _robustness(prices, returns, members, rf, sectors, conn) -> pd.DataFrame:
    """How much do headline numbers move under alternative choices?"""
    rows = []
    # 1. drop the days flagged as extreme moves (possible data artefacts)
    _, r_ex, _, _ = load_inputs(conn, exclude_flagged=True)
    for t in members["ticker"]:
        base, alt = annualised_volatility(returns[t]), annualised_volatility(r_ex[t])
        b0, b1 = beta(returns[t], returns[INDEX]), beta(r_ex[t], r_ex[INDEX])
        if abs(alt - base) > 1e-12 or abs(b1 - b0) > 1e-12:
            rows.append({"test": "exclude_flagged_extreme_days", "name": t,
                         "metric": "ann_volatility", "base": base, "alternative": alt})
            rows.append({"test": "exclude_flagged_extreme_days", "name": t,
                         "metric": "beta", "base": b0, "alternative": b1})
    # 2. sector portfolios from stocks with the full history only (stable membership)
    start_cut = (pd.Timestamp(config.START_DATE) + pd.Timedelta(days=31)).strftime("%Y-%m-%d")
    full_hist = members.loc[members["first_price_date"] <= start_cut, "ticker"].tolist()
    alt_sectors = sector_returns(returns, members, full_hist)
    for c in sectors.columns:
        if c in alt_sectors:
            rows.append({"test": "full_history_members_only", "name": c, "metric": "ann_volatility",
                         "base": annualised_volatility(sectors[c]),
                         "alternative": annualised_volatility(alt_sectors[c])})
            rows.append({"test": "full_history_members_only", "name": c, "metric": "beta",
                         "base": beta(sectors[c], returns[INDEX]),
                         "alternative": beta(alt_sectors[c], returns[INDEX])})
    out = pd.DataFrame(rows)
    out["change"] = out["alternative"] - out["base"]
    return out


def _to_iso(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c.endswith("_date") or c == "date":
            df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v))
                              else str(v)[:10])
    return df


def build(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    prices, returns, members, rf = load_inputs(conn)
    market = returns[INDEX]
    sectors = sector_returns(returns, members)
    sectors_ex_trusts = sector_returns(
        returns, members, members.loc[members["is_investment_trust"] == 0, "ticker"].tolist())
    sectors["All stocks (equal weight)"] = equal_weight_portfolio(returns[members["ticker"]])
    sectors["Financials excl. investment trusts"] = sectors_ex_trusts["Financials"]

    stock = _stock_table(prices, returns, members, rf)
    sector = _sector_table(sectors, members, market, rf)
    index_row = {"sector": "FTSE 100 index (price)", "n_stocks_today": None,
                 **risk_summary(market, prices[INDEX], market, rf)}
    sector = pd.concat([sector, pd.DataFrame([index_row])], ignore_index=True)
    core = sectors.drop(columns=["All stocks (equal weight)", "Financials excl. investment trusts"])
    corr_long, corr_summary = _correlations(core, market)
    # risk_summary already gives corr_with_index; add only the cross-sector average
    sector = sector.merge(corr_summary[["sector", "avg_corr_other_sectors"]], on="sector", how="left")
    rolling = _rolling_correlations(core, market)
    stress = _stress_table(core.assign(**{"All stocks (equal weight)": sectors["All stocks (equal weight)"]}),
                           returns, members, market)
    robust = _robustness(prices, returns, members, rf, core, conn)

    daily = returns.stack().dropna().rename("daily_return").reset_index()
    daily.columns = ["date", "ticker", "daily_return"]
    daily = daily.merge(rf.rename("rf_daily"), left_on="date", right_index=True, how="left")
    daily["excess_return"] = daily["daily_return"] - daily["rf_daily"]
    sector_daily = sectors.stack().dropna().rename("daily_return").reset_index()
    sector_daily.columns = ["date", "sector", "daily_return"]

    tables = {
        "mart_daily_returns": daily,
        "mart_sector_daily_returns": sector_daily,
        "mart_stock_risk": _to_iso(stock),
        "mart_sector_risk": _to_iso(sector),
        "mart_sector_correlation": corr_long,
        "mart_rolling_sector_corr": rolling,
        "mart_stress_periods": stress,
        "mart_robustness": robust,
        "mart_stress_period_definitions": pd.DataFrame(config.STRESS_PERIODS),
    }
    for name, df in tables.items():
        df.to_sql(name, conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_mart_daily_returns ON mart_daily_returns (ticker, date)")
    conn.commit()

    out_dir = config.OUTPUTS_DIR / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ["mart_stock_risk", "mart_sector_risk", "mart_stress_periods", "mart_robustness"]:
        tables[name].round(6).to_csv(out_dir / f"{name.removeprefix('mart_')}.csv", index=False)
    corr_wide = core.corr().round(4)
    corr_wide.to_csv(out_dir / "sector_correlation_matrix.csv")
    return tables
