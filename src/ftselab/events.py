"""Phase 3: event study of Bank of England Bank Rate decisions.

Two questions, two models:
  1. Does the whole market react? The FTSE 100's return on decision days is
     compared with its normal (average) return: a constant-mean model.
  2. Do sectors and stocks react differently from the market? Each series'
     return is compared with what the market model predicts from the FTSE 100's
     return that day: abnormal return = actual - (alpha + beta x market).

Normal behaviour is estimated over trading days -250 to -11 before each
event, leaving out the days around other decisions so one decision cannot
contaminate another. Parameters are fixed at day 0 for the whole event window.

Statistics are computed on one number per event (the event's CAR for a
sector portfolio), so returns of stocks on the same day, which are
correlated, are never treated as independent observations.

Pure functions are at the top and unit tested; build() runs everything.
"""
from __future__ import annotations

import sqlite3
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from . import config
from .risk import load_inputs, sector_returns, equal_weight_portfolio

INDEX = config.INDEX_TICKER
EST_LEN = config.EVENT_EST_FIRST - config.EVENT_EST_LAST + 1  # 240 days


# ----------------------------------------------------------------------------------
# Normal-return models
# ----------------------------------------------------------------------------------

def rolling_market_model(returns: pd.DataFrame, market: pd.Series, exclude: pd.Series,
                         constant_mean: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Alpha and beta for every day t, estimated from days t-250 .. t-11.

    `exclude` marks days (e.g. around decisions) left out of estimation.
    With constant_mean=True, beta is 0 and alpha is the series' mean return.
    """
    r = returns.where(~exclude, axis=0)
    m = market.where(~exclude)
    kw = {"window": EST_LEN, "min_periods": config.EVENT_MIN_EST_OBS}
    if constant_mean:
        alpha = r.rolling(**kw).mean()
        beta = pd.DataFrame(0.0, index=r.index, columns=r.columns).where(alpha.notna())
    else:
        alpha, beta = {}, {}
        for col in r.columns:
            pair = pd.concat([r[col], m], axis=1).dropna().reindex(r.index)
            y, x = pair.iloc[:, 0], pair.iloc[:, 1]
            cov = y.rolling(**kw).cov(x)
            var = x.rolling(**kw).var()
            b = cov / var
            alpha[col] = y.rolling(**kw).mean() - b * x.rolling(**kw).mean()
            beta[col] = b
        alpha, beta = pd.DataFrame(alpha), pd.DataFrame(beta)
    # value on day t uses the window ending on day t-11
    return alpha.shift(config.EVENT_EST_LAST), beta.shift(config.EVENT_EST_LAST)


def event_exclusion_mask(index: pd.Index, event_dates: list[str],
                         before: int = config.EVENT_EXCLUDE_BEFORE,
                         after: int = config.EVENT_EXCLUDE_AFTER) -> pd.Series:
    """True on trading days within [-before, +after] of any event."""
    mask = np.zeros(len(index), dtype=bool)
    pos = index.get_indexer(event_dates)
    for p in pos[pos >= 0]:
        mask[max(0, p - before): p + after + 1] = True
    return pd.Series(mask, index=index)


def abnormal_returns(R: np.ndarray, M: np.ndarray, A: np.ndarray, B: np.ndarray,
                     positions: np.ndarray, offset: int) -> np.ndarray:
    """Abnormal return on day (event + offset), with parameters fixed at day 0.

    R, A, B are (days x series); M is (days,). Returns (events x series);
    NaN where the day is outside the data.
    """
    n = len(M)
    p = positions + offset
    out = np.full((len(positions), R.shape[1]), np.nan)
    ok = (p >= 0) & (p < n)
    out[ok] = R[p[ok]] - A[positions[ok]] - B[positions[ok]] * M[p[ok]][:, None]
    return out


def cumulative_abnormal(R, M, A, B, positions, start: int, end: int) -> np.ndarray:
    """CAR over [start, end]; NaN if any day in the window is missing."""
    return sum(abnormal_returns(R, M, A, B, positions, k) for k in range(start, end + 1))


# ----------------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------------

def summarise(x: np.ndarray) -> dict:
    """Cross-sectional test of mean CAR = 0 across events (one value per event)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    out = {"n_events": n, "mean": np.nan, "median": np.nan, "sd": np.nan, "t_stat": np.nan,
           "p_t": np.nan, "p_wilcoxon": np.nan, "share_positive": np.nan,
           "ci95_low": np.nan, "ci95_high": np.nan}
    if n == 0:
        return out
    out.update(mean=float(x.mean()), median=float(np.median(x)), share_positive=float((x > 0).mean()))
    if n >= 2:
        sd = float(x.std(ddof=1))
        se = sd / np.sqrt(n)
        out.update(sd=sd)
        if se > 0:
            t = out["mean"] / se
            half = stats.t.ppf(0.975, n - 1) * se
            out.update(t_stat=float(t), p_t=float(2 * stats.t.sf(abs(t), n - 1)),
                       ci95_low=out["mean"] - half, ci95_high=out["mean"] + half)
    if n >= 6 and np.any(x != 0):
        out["p_wilcoxon"] = float(stats.wilcoxon(x).pvalue)
    return out


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """False-discovery-rate adjusted p-values (q-values); NaNs are kept."""
    p = np.asarray(p, dtype=float)
    q = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    pv = p[ok]
    m = len(pv)
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adj = np.empty(m)
    adj[order] = np.minimum(ranked, 1.0)
    q[ok] = adj
    return q


def calendar_stratum(dates) -> np.ndarray:
    """Calendar month and week of the month (days 1-7, 8-14, 15-21, 22+), e.g. '08-0'.

    Company results cluster in particular weeks (early Feb, May, Aug, Nov),
    the same weeks as many MPC meetings. Matching placebo days on this
    stratum stops the results season from being mistaken for a rate effect."""
    d = pd.to_datetime(pd.Index(dates))
    week = np.minimum((d.day - 1) // 7, 3)
    return np.array([f"{m:02d}-{w}" for m, w in zip(d.month, week)])


def matched_draws(event_strata: np.ndarray, pool_strata: np.ndarray, draws: int,
                  rng: np.random.Generator, cache: dict | None = None,
                  min_candidates: int = 5) -> np.ndarray:
    """(draws x n) indices into the placebo pool: for each real event, a random
    non-event day from the same calendar stratum (same month if the stratum has
    fewer than `min_candidates` days). Drawn with replacement.

    Cached by the events' strata so every series faces the same placebo dates."""
    key = (tuple(event_strata), draws)
    if cache is not None and key in cache:
        return cache[key]
    pool_month = np.array([s[:2] for s in pool_strata])
    cols = []
    for s in event_strata:
        cands = np.where(pool_strata == s)[0]
        if len(cands) < min_candidates:
            cands = np.where(pool_month == s[:2])[0]
        cols.append(cands[rng.integers(0, len(cands), size=draws)])
    idx = np.stack(cols, axis=1)
    if cache is not None:
        cache[key] = idx
    return idx


def t_pvalues(samples: np.ndarray) -> np.ndarray:
    """Two-sided one-sample t-test p-value for each row of a (draws x n) array."""
    n = samples.shape[1]
    se = samples.std(axis=1, ddof=1) / np.sqrt(n)
    t = samples.mean(axis=1) / se
    return 2 * stats.t.sf(np.abs(t), n - 1)


def _two_sided(actual: float, null: np.ndarray) -> float:
    """2 x the smaller tail share of `null` beyond `actual`, +1 corrected, capped at 1."""
    null = null[~np.isnan(null)]
    if np.isnan(actual) or len(null) == 0:
        return np.nan
    tail = min(np.sum(null <= actual), np.sum(null >= actual))
    return float(min(1.0, (2 * tail + 1) / (len(null) + 1)))


def _t_stat(x: np.ndarray, axis=None):
    with warnings.catch_warnings():  # rows with too little data give NaN
        warnings.simplefilter("ignore", category=RuntimeWarning)
        n = np.sum(~np.isnan(x), axis=axis)
        return np.nanmean(x, axis=axis) / (np.nanstd(x, axis=axis, ddof=1) / np.sqrt(n))


def placebo_pvalue(actual: np.ndarray, pool: np.ndarray, idx: np.ndarray,
                   signs: np.ndarray | None = None) -> tuple[float, float, np.ndarray]:
    """Placebo (randomisation) test of the real events against comparable
    non-event days.

    The placebo distribution is the null. It need not be centred on zero
    (e.g. UK shares go ex-dividend on Thursdays, which pulls the price index
    down on comparable days), so results are compared with that distribution,
    not with zero.

    Returns:
      p_studentised - compares the real t-statistic (mean / standard error)
          with placebo t-statistics. This is the primary test: it stays valid
          when decision days are simply more volatile than normal days, which
          they are (see the volatility test), so extra volatility is not
          mistaken for a directional effect.
      p_mean - compares raw means; shown in the charts because it is easier
          to read, but over-rejects when event days are more volatile.
      means - the placebo means, for charts.

    `actual` holds one value per real event (already signed if needed);
    `pool` one value per placebo day; `idx` is (draws x n) from matched_draws.
    """
    actual = np.asarray(actual, dtype=float)
    actual = actual[~np.isnan(actual)]
    if len(actual) < 2 or idx.size == 0:
        return np.nan, np.nan, np.array([])
    sample = pool[idx]
    if signs is not None:
        sample = sample * signs[None, :]
    with warnings.catch_warnings():  # rows with no data (stock not yet listed) give NaN
        warnings.simplefilter("ignore", category=RuntimeWarning)
        means = np.nanmean(sample, axis=1)
    p_stud = _two_sided(float(_t_stat(actual)), _t_stat(sample, axis=1))
    p_mean = _two_sided(float(actual.mean()), means)
    return p_stud, p_mean, means[~np.isnan(means)]


# ----------------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------------

GROUPS = {
    # name: (description, filter on the events table, sign the CAR?)
    "hike": ("Bank Rate raised", lambda e: e["decision"] == "hike", False),
    "cut": ("Bank Rate cut (scheduled meetings)", lambda e: (e["decision"] == "cut") & (e["is_scheduled"] == 1), False),
    "cut_incl_emergency": ("Bank Rate cut, including March 2020 emergency cuts",
                           lambda e: e["decision"] == "cut", False),
    "hold": ("Bank Rate unchanged", lambda e: e["decision"] == "hold", False),
    "moves_signed": ("All scheduled rate moves, CAR x direction (+ for hikes, - for cuts)",
                     lambda e: (e["decision"] != "hold") & (e["is_scheduled"] == 1), True),
    "all_scheduled": ("Every scheduled decision", lambda e: e["is_scheduled"] == 1, False),
}


# Placebo distributions kept for the chart: one market-level and two sector tests.
PLACEBO_EXAMPLES = {
    (INDEX, "hike", "day0"),
    ("Real Estate", "hike", "m1_p1"),
    ("Utilities", "cut_incl_emergency", "m1_p1"),
}


def _series(conn):
    prices, returns, members, rf = load_inputs(conn)
    sectors = sector_returns(returns, members)
    sectors["All stocks (equal weight)"] = equal_weight_portfolio(returns[members["ticker"]])
    stocks = returns[members["ticker"]]
    return returns[INDEX], sectors, stocks, members


def build(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(config.RANDOM_SEED)
    market, sectors, stocks, members = _series(conn)
    dates = market.index
    events = pd.read_sql_query(
        "SELECT decision_date, event_date, decision, change_bp, is_scheduled, "
        "old_rate_pct, new_rate_pct FROM clean_boe_decisions ORDER BY event_date", conn)
    events = events[events["event_date"].notna()].reset_index(drop=True)
    exclude = event_exclusion_mask(dates, events["event_date"].tolist())

    # Normal-return parameters for each family of series
    fam = {
        "index": (market.to_frame(INDEX), True),
        "sector": (sectors, False),
        "stock": (stocks, False),
    }
    M = market.to_numpy()
    params = {}
    for kind, (frame, const) in fam.items():
        A, B = rolling_market_model(frame, market, exclude, constant_mean=const)
        Mk = np.zeros_like(M) if const else M
        params[kind] = (frame.to_numpy(), Mk, A.to_numpy(), B.to_numpy(), list(frame.columns))

    pos = dates.get_indexer(events["event_date"])
    # an event is usable if day-0 parameters exist for the index
    usable = ~np.isnan(params["index"][2][pos, 0])
    events["included"] = usable.astype(int)
    events["exclusion_reason"] = np.where(usable, "", "fewer than 150 estimation days (first months of 2010)")
    ev = events[usable].reset_index(drop=True)
    ev_pos = pos[usable]

    # Placebo pool: non-event Thursdays outside any decision's window, with parameters
    weekday = pd.to_datetime(dates).weekday
    cand = np.where((weekday == config.PLACEBO_WEEKDAY) & ~exclude.to_numpy()
                    & ~np.isnan(params["index"][2][:, 0]))[0]
    cand = cand[cand + max(e for _, e in config.EVENT_WINDOWS.values()) < len(dates)]
    pool_strata = calendar_stratum(dates[cand])
    ev_strata = calendar_stratum(ev["event_date"])
    draws = config.PLACEBO_DRAWS

    car_rows, result_rows, path_rows, vol_rows, calib_rows, example_rows = [], [], [], [], [], []
    cache: dict = {}
    for kind, (R, Mk, A, B, names) in params.items():
        for wname, (s, e) in config.EVENT_WINDOWS.items():
            car_ev = cumulative_abnormal(R, Mk, A, B, ev_pos, s, e)       # events x series
            car_pool = cumulative_abnormal(R, Mk, A, B, cand, s, e)       # candidates x series
            for j, name in enumerate(names):
                for i in range(len(ev)):
                    car_rows.append((ev.at[i, "event_date"], ev.at[i, "decision"],
                                     int(ev.at[i, "is_scheduled"]), kind, name, wname, car_ev[i, j]))
                for g, (desc, filt, signed) in GROUPS.items():
                    sel = filt(ev).to_numpy()
                    x = car_ev[sel, j]
                    sign = np.sign(ev.loc[sel, "change_bp"].to_numpy()) if signed else None
                    if signed:
                        x = x * sign
                    keep = ~np.isnan(x)
                    if kind == "stock" and keep.sum() < config.EVENT_MIN_EVENTS_STOCK:
                        continue  # too few events (e.g. a recent listing) to say anything
                    res = summarise(x)
                    idx = matched_draws(ev_strata[sel][keep], pool_strata, draws, rng, cache)
                    p_pl, p_pl_mean, means = placebo_pvalue(x[keep], car_pool[:, j], idx,
                                                            sign[keep] if signed else None)
                    if (name, g, wname) in PLACEBO_EXAMPLES:
                        example_rows += [{"series": name, "group": g, "window": wname,
                                          "actual_mean": res["mean"], "placebo_mean": v,
                                          "p_placebo": p_pl} for v in means]
                    result_rows.append({
                        "kind": kind, "series": name, "group": g, "group_description": desc,
                        "window": wname, **res, "p_placebo": p_pl, "p_placebo_mean": p_pl_mean,
                        "placebo_centre": float(np.median(means)) if len(means) else np.nan,
                        "placebo_mean_sd": float(np.std(means)) if len(means) else np.nan,
                    })

            # Abnormal volatility on decision days: are moves bigger than usual,
            # in either direction? Mean squared abnormal return on scheduled
            # decision days vs calendar-matched placebo days.
            if wname == "day0" and kind != "stock":
                sched = (ev["is_scheduled"] == 1).to_numpy()
                for j, name in enumerate(names):
                    ok = sched & ~np.isnan(car_ev[:, j])
                    ev_sq = car_ev[ok, j] ** 2
                    pool_sq = car_pool[:, j] ** 2
                    idx = matched_draws(ev_strata[ok], pool_strata, draws, rng, cache)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        pl = np.nanmean(pool_sq[idx], axis=1)
                    matched_normal = float(np.nanmean(pl))
                    vol_rows.append({
                        "kind": kind, "series": name, "n_events": int(ok.sum()),
                        "rms_ar_event": float(np.sqrt(ev_sq.mean())),
                        "rms_ar_matched_placebo": float(np.sqrt(matched_normal)),
                        "variance_ratio": float(ev_sq.mean() / matched_normal),
                        "variance_ratio_vs_all_thursdays": float(ev_sq.mean() / np.nanmean(pool_sq)),
                        "median_abs_ratio": float(np.median(np.sqrt(ev_sq))
                                                  / np.nanmedian(np.sqrt(pool_sq[idx]))),
                        "p_placebo_one_sided": float((np.sum(pl >= ev_sq.mean()) + 1) / (len(pl) + 1)),
                        "placebo_ratio_p95": float(np.quantile(pl, 0.95) / matched_normal),
                    })

                # calibration: how often does the t-test reject on placebo dates?
                for g in ["hike", "hold"]:
                    sel = GROUPS[g][1](ev).to_numpy()
                    idx = matched_draws(ev_strata[sel], pool_strata, draws, rng, cache)
                    for j, name in enumerate(names):
                        smp = car_pool[:, j][idx]
                        rate = float((t_pvalues(smp) < 0.05).mean())
                        calib_rows.append({"kind": kind, "series": name, "group_size_like": g,
                                           "n_events": int(sel.sum()), "draws": draws,
                                           "false_positive_rate_5pct": rate})

        # average abnormal-return path around events, by group (index and sectors)
        if kind != "stock":
            lo, hi = config.EVENT_PATH_DAYS
            for g in ["hike", "cut", "hold"]:
                sel = GROUPS[g][1](ev).to_numpy()
                cum = None
                for k in range(lo, hi + 1):
                    ar = abnormal_returns(R, Mk, A, B, ev_pos[sel], k)
                    cum = ar if cum is None else cum + ar  # cumulative from day lo
                    for j, name in enumerate(names):
                        x = cum[:, j]
                        x = x[~np.isnan(x)]
                        se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
                        path_rows.append({"kind": kind, "series": name, "group": g, "day": k,
                                          "mean_car_from_start": x.mean() if len(x) else np.nan,
                                          "se": se, "n_events": len(x)})

    results = pd.DataFrame(result_rows)
    # Multiple testing: Benjamini-Hochberg across each family of tests.
    # The placebo p-value is the primary test (it needs no assumption that
    # abnormal returns average zero on normal days); the t-test is reported too.
    # Families: market + sectors together; stocks separately.
    results["family"] = np.where(results["kind"] == "stock", "stock", "market_and_sector")
    for col_p, col_q in [("p_placebo", "q_fdr_placebo"), ("p_t", "q_fdr_t")]:
        results[col_q] = np.nan
        for fam_name in results["family"].unique():
            m = (results["family"] == fam_name) & results[col_p].notna()
            results.loc[m, col_q] = benjamini_hochberg(results.loc[m, col_p].to_numpy())

    vol = pd.DataFrame(vol_rows)
    if not vol.empty:
        vol["q_fdr"] = benjamini_hochberg(vol["p_placebo_one_sided"].to_numpy())

    tables = {
        "mart_event_list": events,
        "mart_event_car": pd.DataFrame(car_rows, columns=[
            "event_date", "decision", "is_scheduled", "kind", "series", "window", "car"]),
        "mart_event_results": results,
        "mart_event_path": pd.DataFrame(path_rows),
        "mart_event_volatility": vol,
        "mart_event_calibration": pd.DataFrame(calib_rows),
        "mart_event_placebo_pool": pd.DataFrame({"date": dates[cand]}),
        "mart_event_placebo_examples": pd.DataFrame(example_rows),
    }
    for name, df in tables.items():
        df.to_sql(name, conn, if_exists="replace", index=False)
    conn.commit()

    out_dir = config.OUTPUTS_DIR / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    tables["mart_event_list"].to_csv(out_dir / "event_list.csv", index=False)
    results[results["kind"] != "stock"].round(6).to_csv(out_dir / "event_results.csv", index=False)
    results[(results["kind"] == "stock") & (results["window"] == "day0")].round(6).to_csv(
        out_dir / "event_results_stocks.csv", index=False)
    tables["mart_event_volatility"].round(6).to_csv(out_dir / "event_volatility.csv", index=False)
    tables["mart_event_calibration"].round(4).to_csv(out_dir / "event_calibration.csv", index=False)
    return tables
