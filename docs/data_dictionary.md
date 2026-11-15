# Data dictionary

Database: `data/ftse_lab.db` (SQLite, built by `python run_pipeline.py`).
Tables starting `raw_` hold data exactly as downloaded; tables starting
`clean_` are built from them by the SQL files in `sql/clean/`.

## Raw layer

| Table | Contents |
|---|---|
| `raw_prices` | Yahoo daily rows: ticker, date, open, high, low, close, adj_close, volume, downloaded_at |
| `raw_ticker_info` | ticker, quote currency (GBp = pence), exchange |
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
