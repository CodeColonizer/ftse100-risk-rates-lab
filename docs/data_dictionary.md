# Data dictionary

Database: `data/ftse_lab.db` (SQLite, built by `python run_pipeline.py`).
Tables starting `raw_` hold data exactly as downloaded; tables starting
`clean_` are built from them by the SQL files in `sql/clean/`.

## Raw layer

| Table | Contents |
|---|---|
| `raw_prices` | Yahoo daily rows: ticker, date, open, high, low, close, adj_close, volume, downloaded_at |
| `raw_ticker_info` | ticker, quote currency (GBp = pence), exchange |
| `raw_dividends` | ticker, date (ex-dividend date), dividend in the quote currency |
| `raw_fx` | pair (`GBPUSD=X`, `GBPEUR=X`), date, rate (foreign currency per pound) |
| `raw_price_corrections` | `data/reference/price_corrections.csv` |
| `raw_constituents` | the constituents snapshot CSV |
| `raw_boe_decisions` | `data/reference/boe_bank_rate_decisions.csv` |
| `raw_bank_rate_daily` | BoE series IUDBEDR: date, bank_rate_pct |

## Clean layer

### `clean_trading_calendar`
One row per London trading day (days with a FTSE 100 index level). `date`.

### `clean_prices` — one row per ticker per trading day
| Column | Meaning |
|---|---|
| `ticker` | Yahoo ticker, e.g. `AZN.L`; `^FTSE` is the index |
| `date` | trading day (YYYY-MM-DD) |
| `quote_currency` | currency Yahoo quotes the line in (`GBp`, `USD`, `EUR`, or `index points`) |
| `open`, `high`, `low`, `close` | prices in pence (converted if quoted in USD/EUR) |
| `adj_close` | close adjusted for dividends and splits, in pence: **use this for returns** |
| `volume` | shares traded |
| `was_corrected` | 1 if a documented correction (`price_corrections.csv`) changed the row |
| `is_unit_shift` | 1 if a ~100x level change that does not reverse (should never happen; a test fails) |
| `is_extreme_move` | 1 if the day's move exceeds 25% (kept, for review) |
| `is_stale` | 1 if volume is zero and the close is unchanged (kept, for review) |

### `clean_price_exclusions`
Every raw row removed from `clean_prices`: ticker, date, close, adj_close,
prev_ratio, reason.

### `clean_prices_flagged`
Working table: all candidate rows with every flag, before removals. Useful
for auditing the cleaning rules.

### `clean_constituents` — one row per company
epic, ticker, company, isin, icb_sector, icb_industry, is_investment_trust,
snapshot_date, currency, first_price_date, last_price_date, n_price_days,
n_missing_days (trading days between first and last price with no price).

### `clean_dividends` — one row per dividend
ticker, ex_date, dividend_quote_currency, dividend_pence (same units as
clean_prices), dividend_yield_on_day (dividend / previous close),
was_corrected, matched_to_price, within_price_history.

### `clean_total_returns` — one row per clean price
ticker, date, dividend (pence going ex that day), price_return, total_return.
**Use total_return for all return calculations.** A return is NULL on a
stock's first day and after any gap in its prices.

### `clean_boe_decisions` — one row per MPC decision since 2010
| Column | Meaning |
|---|---|
| `decision_date` | announcement date |
| `event_date` | first trading day on or after the announcement |
| `old_rate_pct`, `new_rate_pct` | Bank Rate before and after, in % |
| `change_bp` | change in basis points (25 = 0.25 percentage points) |
| `decision` | `hike`, `cut` or `hold` |
| `is_scheduled` | 0 for the emergency meetings of 11 and 19 March 2020 |
| `iudbedr_rate_pct` | official daily Bank Rate on the decision date (cross-check) |

### `clean_bank_rate_daily`
date, bank_rate_pct: Bank Rate in force on each trading day.

## Analytics layer (Phase 2)

Built by `src/ftselab/risk.py`. All returns are fractions (0.05 = 5%).

| Table | Contents |
|---|---|
| `mart_daily_returns` | ticker, date, daily_return, rf_daily (Bank Rate as a daily return), excess_return |
| `mart_sector_daily_returns` | date, sector, daily_return of the equal-weighted sector portfolio |
| `mart_stock_risk` | one row per stock and the index: first/last date, n_returns, years, ann_return, ann_volatility, sharpe, beta, corr_with_index, worst_day_return/date, max_drawdown, peak/trough/recovery dates, days_to_recover, short_history (under 3 years) |
| `mart_sector_risk` | the same metrics per sector, plus n_stocks_today and avg_corr_other_sectors; includes "All stocks (equal weight)", "Financials excl. investment trusts" and the index for comparison |
| `mart_sector_correlation` | sector_a, sector_b, correlation (full period, daily returns) |
| `mart_rolling_sector_corr` | date, sector, corr_with_index over the previous 252 trading days |
| `mart_stress_periods` | per period and sector, index or stock: window_return, vs_index, max_drawdown_in_window, ann_volatility_in_window; `summary` rows give avg_pairwise_sector_corr in `value` |
| `mart_stress_period_definitions` | period, label, base_date, end_date, why |
| `mart_robustness` | test, name, metric, base, alternative, change |

The small tables are also saved as CSVs in `outputs/tables/`.

## Event study (Phase 3)

Built by `src/ftselab/events.py`. Abnormal returns are fractions (0.01 = 1%).

| Table | Contents |
|---|---|
| `mart_event_list` | every decision with included (1/0) and the reason if excluded |
| `mart_event_car` | event_date, decision, is_scheduled, kind (index/sector/stock), series, window, car (cumulative abnormal return) |
| `mart_event_results` | per kind, series, group (hike, cut, cut_incl_emergency, hold, moves_signed, all_scheduled) and window: n_events, mean, median, sd, t_stat, p_t, p_wilcoxon, share_positive, 95% interval, p_placebo (studentised, primary), p_placebo_mean, placebo_centre, family, q_fdr_placebo, q_fdr_t |
| `mart_event_volatility` | per series: rms abnormal return on decision days and on matched placebo days, variance_ratio, median_abs_ratio, p_placebo_one_sided, q_fdr |
| `mart_event_calibration` | how often the t-test rejects at 5% on placebo samples |
| `mart_event_path` | average cumulative abnormal return by day from −5 to +5, per group |
| `mart_event_placebo_pool` | the non-decision Thursdays used as placebo days |
| `mart_event_placebo_examples` | placebo distributions for the three tests in the placebo chart |

Small tables are also saved as CSVs in `outputs/tables/` (`event_*.csv`).

## App data (Phase 4)

Written by `src/ftselab/app_data.py` to `app/data/` (not committed to `main`;
published daily to the `streamlit-app` branch). Summary tables only: no raw
prices.

| File | Contents |
|---|---|
| `meta.json` | data date, build time, counts, Bank Rate now, last decision, quality summary |
| `sector_risk.csv`, `stock_risk.csv` | risk metrics (from the `mart_` tables) |
| `sector_growth.csv` | growth of 100 per sector, the equal-weighted market and the FTSE 100, weekly |
| `sector_correlation.csv`, `rolling_corr.csv` | correlations (rolling sampled weekly) |
| `stress_periods.csv`, `stress_definitions.csv` | stress-period results and definitions |
| `event_results.csv`, `event_stock_results.csv`, `event_volatility.csv`, `event_path.csv` | event-study results |
| `boe_decisions.csv` | Bank Rate decisions, with whether each is in the event study |
| `quality_report.csv` | the latest data quality report |
