# Reference data sources

These small public files are committed so the project is reproducible. Raw
price data is **not** committed; `python run_pipeline.py` downloads it.

| File | What it is | Source | Retrieved |
|---|---|---|---|
| `ftse100_constituents_2026-11-15.csv` | The 100 FTSE 100 companies, with EPIC code, ISIN, ICB sector, mapped ICB industry and Yahoo ticker | Wikipedia, [FTSE 100 Index](https://en.wikipedia.org/wiki/FTSE_100_Index), constituents table | 15 Nov 2026 |
| `boe_bank_rate_decisions.csv` | Every MPC Bank Rate decision since Jan 2010: date, old rate, new rate, change, hike/cut/hold, scheduled or not | Bank of England, [MPC voting history (mpcvoting.xlsx)](https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy-summary-and-minutes/mpcvoting.xlsx) | Regenerated on each pipeline run (last: 15 Nov 2026) |
| `price_corrections.csv` | Three documented fixes to Yahoo price histories, with reasons and evidence | Our own data checks (see `docs/phase1_findings.md`) | 15 Nov 2026 |

## How each file was checked

**Constituents.** Cross-checked against FTSE Russell's 2026 index review
announcements: the list includes the September 2026 additions (easyJet,
Ithaca Energy) and the June/March additions (Aberdeen, Computacenter,
Investec, IG Group, Lion Finance), and excludes the companies those reviews
removed (Entain, Persimmon, Berkeley, Mondi, Rightmove, Hikma). The snapshot
reflects the index after the review effective 21 September 2026; the next
review (December 2026) is not reflected.
Sources: [LSEG, September 2026 review](https://www.lseg.com/en/media-centre/press-releases/2026/ftse-uk-index-series-review-september-2026),
[June 2026 review](https://www.lseg.com/en/media-centre/press-releases/ftse-russell/2026/ftse-uk-index-series-review-june-2026),
[March 2026 review](https://www.lseg.com/en/media-centre/press-releases/ftse-russell/2026/ftse-uk-index-series-review-march-2026).

**BoE decisions.** Every decision is checked automatically against the Bank's
official daily Bank Rate series (IADB code `IUDBEDR`): the new rate must equal
the published rate on the decision day, and every change in the daily series
must fall on a decision date. Both checks pass.

## Downloaded (not committed)

| Data | Source | Notes |
|---|---|---|
| Daily prices from 4 Jan 2010 (first trading day of 2010), 100 stocks + `^FTSE` | Yahoo Finance via the `yfinance` library | Unofficial data; open, high, low, close, adjusted close, volume |
| Quote currency per ticker | Yahoo Finance | Three lines are quoted in USD or EUR |
| GBP/USD and GBP/EUR daily rates | Yahoo Finance (`GBPUSD=X`, `GBPEUR=X`) | Used to convert those lines to pence |
| Daily Bank Rate | Bank of England IADB, series `IUDBEDR` | Risk-free rate for Phase 2 |
