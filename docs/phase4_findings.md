# Phase 4: daily refresh and interactive app

**Status:** complete, 15 November 2026.

## What was built

1. **A daily automated refresh** (GitHub Actions,
   [`.github/workflows/daily-refresh.yml`](../.github/workflows/daily-refresh.yml)).
   Every weekday at 18:30 UTC, after the London close, it downloads fresh
   prices, dividends and Bank of England data, reruns the full pipeline
   (cleaning, 40 data quality checks, risk analytics and event study), runs all
   tests, and only then publishes the app with its new data.
2. **An interactive Streamlit app** ([`app/streamlit_app.py`](../app/streamlit_app.py)),
   deployed on Streamlit Community Cloud from the `streamlit-app` branch. It has
   six tabs: Overview, Sector risk, Diversification, Stress periods, Bank Rate
   decisions, and Data & method.
3. **A test workflow** ([`.github/workflows/tests.yml`](../.github/workflows/tests.yml))
   that runs the unit tests on every push and pull request.

## How the pieces fit

```
main branch (code, docs)                    streamlit-app branch (generated)
        |                                              ^
        |  weekdays 18:30 UTC, or a code push           |  force-pushed only if
        v                                              |  everything passed
GitHub Actions: download -> clean -> 40 quality checks -> risk + event study
                -> export app/data (summary tables) -> 119 tests -> publish
                                                               |
                                    Streamlit Community Cloud redeploys the app
```

- **Fail-safe.** If a download fails, a required data quality check fails, or
  any test fails, nothing is published: the live app keeps the last good data
  and the failed run is visible in the Actions tab.
- **No raw prices are published.** The app reads summary tables only (risk
  metrics, weekly sector growth indices, correlations, stress and event-study
  results, quality status), 0.9 MB in total. A test fails if any published
  table has price columns.
- **Text stays true after each refresh.** Every number in the app's text is
  calculated from the data, not typed in. The findings pages in `docs/` are
  dated snapshots and say so.
- **`main` stays clean.** Daily data goes to a separate branch that is
  replaced on each run, so `main`'s history contains only real changes.

## What the app shows

| Tab | Content |
|---|---|
| Overview | Bank Rate, data date, data quality status; key findings written from live data; growth of £100 |
| Sector risk | Choose a measure (volatility, worst fall, beta, Sharpe, return); compare sector growth; sector and stock tables with a sector filter |
| Diversification | Beta vs correlation map; sector correlation heatmap; rolling correlation for a chosen sector with stress periods shaded |
| Stress periods | Sector returns in each period, with the FTSE 100 for reference; best and worst five stocks |
| Bank Rate decisions | Bank Rate history; extra volatility on decision days; sector reactions by decision type and window with confidence intervals and significance; the FTSE 100's path around decisions |
| Data & method | Data quality results, items flagged for review, method and limitations, links to the full write-up |

All charts have tooltips, follow the viewer's light or dark theme and work on
a phone-width screen.

## Testing

- `tests/test_app.py` checks the published data (no raw price columns, under
  5 MB, all tables present, growth series start at 100, zero failed quality
  checks). It also runs the whole app headless with Streamlit's `AppTest` and
  fails on any error.
- The app was also checked by hand in a browser at desktop and phone widths.
- Total: 119 tests.

## Operating notes

- **Run it by hand:** Actions tab → "Daily data refresh" → "Run workflow".
- **If a run fails:** open the run, read the failing step's log, and download
  the `outputs-N` artifact (charts, tables and `data_quality_report.csv`). The
  live app is unaffected until a run succeeds.
- **Yahoo Finance from GitHub's servers:** Yahoo sometimes limits automated
  requests. The downloader retries; if data is still incomplete, the quality
  checks stop the run.
- **Constituents** are not refreshed automatically: after an index review
  (March, June, September, December), run
  `python run_pipeline.py --refresh-constituents`, check the new snapshot, and
  commit it.
- **Run the app locally:** `python run_pipeline.py`, then
  `streamlit run app/streamlit_app.py`.

## Limitations

- The app is only as fresh as the last successful run. The header shows the
  data date and the build time.
- Streamlit Community Cloud apps go to sleep after a period without visitors.
  The first visit after that takes a few seconds to wake up.
- The findings pages (`docs/phase*_findings.md`) describe the data as of
  15 November 2026; the app's figures will drift from them as new data
  arrives.
