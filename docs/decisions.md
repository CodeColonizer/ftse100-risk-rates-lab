# Decision log

A short record of each important decision and why it was made. Newest phase last.

## Phase 1: data pipeline and quality (November 2026)

**1. Universe = today's FTSE 100 members, back to 2010.**
Why: free, reliable historical index membership is not available, and the
business question is about the stocks an investor can buy today.
Trade-off: **survivorship bias.** Companies that fell out of the index, were
taken over or failed (e.g. Entain, Persimmon, Hikma, Royal Mail) are missing,
so historical risk will look lower and returns higher than an investor
holding "the FTSE 100" at the time would have seen. Every later finding is
labelled as being about today's constituents.

**2. Sector = ICB Industry (11 groups), not ICB Sector (~40).**
Why: with 100 stocks, most ICB sectors hold one to three companies, which is
too few for stable sector statistics. Industry keeps groups of 3 to 25.
Trade-off: Financials (25 stocks, including 5 investment trusts) is broad;
investment trusts are flagged (`is_investment_trust`) so they can be excluded.
Sector labels are today's, so applying them to 2010 is a mild form of
**look-ahead bias** (a few firms changed business mix over the period).

**3. Constituents from a dated, committed snapshot, refreshed only on request.**
Why: the source (Wikipedia) can be edited by anyone. A dated file makes every
run reproducible and auditable. It was cross-checked against FTSE Russell's
2026 review announcements before committing.

**4. Bank Rate decisions from the Bank of England's own MPC voting file.**
Why: the official "Bank Rate history" page only lists changes. Holds matter
for Phase 3 (a hold can surprise markets too), and the MPC voting file lists
every meeting. Each decision is checked against the separate official daily
series (IUDBEDR). The two emergency Covid cuts (11 and 19 March 2020) are
marked `is_scheduled = 0` because unscheduled decisions behave differently in
an event study.

**5. Event date = the announcement date.**
Why: MPC decisions are published at 12:00 UK time, before the London close at
16:30, so the same day's closing price already reflects the news.

**6. SQLite with `raw_` and `clean_` tables, cleaning written in SQL.**
Why: no server needed, a single file, and the same pattern as my previous
project. Keeping the raw layer untouched means any cleaning rule can be
changed and rerun without downloading again. SQL makes the rules easy to read.

**7. Total returns (price plus dividends); both close and adjusted close kept.**
Originally: Yahoo's adjusted close, on the assumption that it includes
dividends. **Superseded by decision 25:** for London stocks it barely does, so
returns are now built from the close plus dividends. Why total returns: they
reflect what a shareholder earned. The FTSE 100 index (`^FTSE`) is a price
index without dividends, which understates the market's return; a
total-return index is not freely available. Noted as a limitation.

**8. Lines quoted in USD or EUR are converted to pence.**
Why: Yahoo serves Compass and InterContinental Hotels in US dollars (for the
whole history) and Metlen in euros. For a sterling investor, a return should
include the currency effect, and the benchmark index is in sterling. We
convert at the latest daily GBP/USD or GBP/EUR rate on or before each day.

**9. No forward-filling of missing prices.**
Why: filling a gap with yesterday's price invents a 0% return, which
understates volatility and distorts correlations. Missing days stay missing
and are counted (26 across all stocks in the source data; 67 after the
carried-forward rows in decision 24 are also treated as missing).

**10. Remove a price only for a clear, documented reason; otherwise flag it.**
- *Removed*: (a) one-day ~100x jumps that reverse (pence/pound glitches; none
  found this run), (b) "flat-bar" bad prints: open = high = low = close, a move
  over 15%, and the next day back within 5% (5 rows, all in early 2010),
  (c) history before a documented usable date (see 11).
- *Flagged and kept*: one-day moves over 25% (24 rows, mostly genuine, e.g.
  Covid crash, vaccine news on 9 Nov 2020), zero-volume unchanged days
  (unless many stocks show one on the same day: see decision 24).
Why: genuine extreme days are exactly what risk analysis is about, so they
must not be "cleaned away". The flat-bar rule separates bad prints from real
volatility: real volatile days have a real intraday range.
Every removed row is kept in `clean_price_exclusions` with its reason.

**11. Three manual corrections, kept in a committed CSV with evidence.**
`data/reference/price_corrections.csv`: Polar Capital Technology (Yahoo
missed a 10-for-1 split adjustment before Jan 2013), Lion Finance (history
before its Feb 2012 premium listing is in a different unit), Endeavour Mining
(barely traded before its June 2021 London listing). Why a file, not code:
anyone can see and challenge each fix, and a test fails if a correction stops
having any effect.

**12. Data quality checks are SQL queries shared by the pipeline and pytest.**
Why: one definition, so the report and the tests can never disagree. Checks
are "error" (pipeline fails) or "warning" (reported for review).

**13. Python 3.15 instead of the planned 3.12.**
Why: the Python 3.12 registered on this machine points to a broken Anaconda
install; 3.15 works and is what my previous project uses. Phase 4 must check
which Python versions Streamlit Community Cloud offers and pin a compatible one.

## Phase 2: risk analytics (November 2026)

**14. Simple daily returns, no bridging of gaps.**
Why: simple returns average correctly across stocks, which is how the sector
portfolios are built. A return is only calculated between two consecutive
trading days, so a missing day never produces a two-day return disguised as
one day. Each of the 67 missing stock-days (including 41 removed carried-forward
prices) and 5 removed bad prints costs one or two
returns, out of about 400,000.

**15. Bank Rate on each day as the risk-free rate.**
Why: Bank Rate ranged from 0.1% to 5.25%. A single average would flatter
Sharpe ratios after 2022 and penalise them before. Bank Rate is the UK policy
rate and the cleanest free daily series; a 3-month gilt yield would be an
alternative.

**16. Equal-weighted sector portfolios, rebalanced daily.**
Why: shares-in-issue history is not freely available, so market-cap weights
cannot be built reliably. Equal weighting answers "what does a typical stock
in this sector do?" rather than "what do the sector's giants do?". The
difference is visible in 2022, when the index rose 0.9% but the
equal-weighted portfolio fell 7.5%.

**17. Sectors use all members available on each day.**
Why: dropping late joiners would leave Health Care, Energy and Telecoms with
two or three stocks. A robustness check rebuilds sectors from the 86
full-history stocks only; volatility changes by at most 0.8 points.

**18. Investment trusts kept in Financials, with an alternative row.**
Why: they are genuine FTSE 100 members, but they hold diversified portfolios
rather than run a financial business. The sector table includes
"Financials excl. investment trusts" so the difference can be seen.

**19. Beta and correlation against the FTSE 100 price index.**
Why: it is the benchmark people quote. Dividends barely affect daily
co-movement, so beta and correlation are reliable; the index's return and
Sharpe ratio are understated, and this is stated wherever they appear.

**20. Fixed, dated stress windows chosen in advance from public events.**
Why: choosing windows by searching the data for the worst days would
exaggerate results. Each window is defined in `config.py` with a one-line
reason: Covid crash (19 Feb to 23 Mar 2020), 2022 rate hikes (calendar 2022),
mini-budget (22 Sep to 14 Oct 2022). Windows run close to close.

**21. One-year (252-day) rolling correlations, at least 200 days of data.**
Why: one year is long enough to be stable and short enough to show regime
changes such as Energy decoupling in 2026.

**22. Flagged days kept in the headline results, tested separately.**
Why: Phase 1 kept 24 large moves because most are genuine. The robustness
table shows the effect of removing them (average change of 1.3 volatility
points for the 20 stocks affected), so the choice is visible, not hidden.

**23. Results stored as `mart_` tables plus small CSVs.**
Why: Phase 3 and the Phase 4 app can read the same tables, and reviewers can
open the CSVs on GitHub without running anything.

**24. Remove prices carried forward on a market-wide stale day (a Phase 1 fix
found during Phase 2).**
On 11 July 2017, 41 stocks show zero volume and exactly the previous close,
while the index moved −0.5%. The source had no data that day and repeated
yesterday's price, which would create false 0% returns, the same problem as
forward-filling (decision 9). Rule: if 10 or more stocks are stale on the same
day, those stale rows are removed and logged; a single illiquid stock with a
quiet day is still kept. A required check now fails if such a day reappears.
Effect on results: no sector figure changes by more than 0.01.

## Phase 3: event study of Bank Rate decisions (November 2026)

**25. Build total returns from close + dividends; do not trust Yahoo's adjusted
close for London stocks (a Phase 1 fix found during Phase 3).**
While checking the event study, I found that Yahoo's adjusted close for HSBC
differs from its raw close by under 1% over 16 years, although HSBC paid
several percent a year in dividends. Yahoo's dividend records themselves are
correct (yields of 1–4% per payment), so the pipeline now downloads them and
calculates total return = (close + dividend on its ex-date) / previous close
− 1, in SQL (`sql/clean/05_total_return.sql`). One scaling error was found and
corrected in `price_corrections.csv`: Melrose dividends before its January
2016 share consolidation were about 7 times too large (scaled by Yahoo's own
7/48 ratio). New checks: a required check that no dividend is under 0.02% or
over 50% of the price (a pence/pound mix-up), and review lists of dividends
over 10% and stock-years over 20% (special returns of capital such as Aviva
2022 and Tesco 2021). Effect: annual returns rose 3–6 points per sector and
Sharpe ratios with them; volatility, beta and correlation barely moved. The
Phase 2 findings were corrected and say so at the top.

**26. Two levels of question, two models.**
A Bank Rate decision hits the whole market, so a market-model abnormal return
(stock minus what the FTSE 100 predicts) cannot show a market-wide reaction:
it only shows rotation between sectors. So: (1) market level, the FTSE 100
against its own normal average return (constant-mean model); (2) sector and
stock level, the market model against the FTSE 100.

**27. Estimation window: trading days −250 to −11, leaving out other decisions.**
Why: about one year of normal behaviour, ending two weeks before the event so
any build-up is not treated as normal. Days −1 to +5 around every other
decision are left out, because the MPC met every 4–6 weeks and those days are
not "normal". Parameters are fixed at day 0 for the whole event window. The
first 11 decisions of 2010 have too little history and are excluded.

**28. Event windows: day 0, days −1 to +1, days 0 to +5.**
Why: the decision is announced at noon, so day 0's close carries the news;
−1 to +1 allows for leaks and slow reactions; 0 to +5 tests for drift.

**29. One number per event, not per stock.**
Stocks react on the same day, so their returns are correlated. Treating 100
stocks × 17 hikes as 1,700 independent observations would overstate
significance. Tests use the sector portfolio's return for each event.

**30. Placebo test as the primary test, matched to the calendar and
studentised.** Three refinements, each found by checking the results:
- *Placebo days are Thursdays without a decision* (156 of 164 decisions were
  on Thursdays), drawn 2,000 times.
- *Matched on month and week of the month.* Company results and big
  ex-dividend dates cluster in early February, May, August and November, the
  same weeks as many MPC meetings. Matching stops those from being mistaken
  for rate effects.
- *Compared with the placebo distribution, not with zero.* 73% of dividend
  ex-dates fall on Thursdays, so the price index averages −5.4 basis points on
  Thursdays against +0.4 to +8.0 on other days. Comparable days are therefore
  not centred on zero.
- *Studentised (compares t-statistics, not raw averages).* Decision days are
  more volatile than normal days (decision 32), which on its own makes raw
  averages look "significant". With the studentised version, 3.0% of market
  and sector tests fall below p = 0.05, close to the 5% expected by chance;
  with raw averages it was 9.8%.
The ordinary t-test is reported too, but a calibration check showed it
rejects 7% (hike-sized samples) to 17% (hold-sized samples) of placebo samples
at the 5% level, so it is not used for conclusions.

**31. Correct for multiple testing (Benjamini–Hochberg, 10% false discovery
rate).** Why: 234 market and sector tests (13 series × 6 groups × 3 windows)
would produce about 12 "significant" results at p < 0.05 by chance alone.
Stocks (1,776 tests) are a separate family and only reported as a whole.

**32. Test whether decisions make prices move more, not only in which
direction.** Why: markets anticipate most decisions, so the direction of a
reaction depends on the surprise, which decision type alone does not capture.
A bigger-than-usual move in either direction (variance ratio, against the same
matched placebo days) shows whether decisions carry news at all.

**33. Keep the March 2020 emergency cuts separate.** They coincided with the
Covid crash, so any reaction cannot be attributed to the rate cut. Main cut
results use the 7 scheduled cuts; a separate group includes all 9.

**34. No measure of the surprise.** A proper surprise measure needs
market-implied rate expectations (e.g. overnight index swaps), which are not
freely available as a clean daily series. This is the main limitation and the
natural next step.

## Phase 4: daily refresh and app (November 2026)

**35. Publish the app and its data to a generated `streamlit-app` branch.**
Why: committing data every weekday to `main` would bury real changes under
daily bot commits. The workflow builds the app with fresh data and
force-pushes it to a separate branch, which Streamlit Community Cloud deploys
from. `main` holds only code and docs; the generated branch is replaced on
every run and should never be edited.

**36. Publish only if everything passes.**
Why: an app that silently shows broken data is worse than one that is a day
old. Downloads, all required data quality checks and all tests must succeed
before anything is published; otherwise the live app keeps the last good data
and the failed run is visible in the Actions tab.

**37. The app reads summary tables, not raw prices.**
Why: the project rule is not to publish raw price data, and the app does not
need it. It reads risk metrics, weekly sector growth indices (sector level,
derived), correlations and test results: 0.9 MB in total. A test enforces
that no published table has price columns.

**38. Every number in the app's text is calculated, not typed.**
Why: the data changes daily. Sentences such as "the two riskiest sectors"
are written from the current tables, so they cannot go stale. The findings
pages in `docs/` are dated snapshots and say so.

**39. Schedule: weekdays at 18:30 UTC.**
Why: after the London close (16:30 UK time in both GMT and BST) and after
Yahoo has published the day's closing prices. Also runs on any push to `main`
that changes code or reference data, so code changes reach the app at once.

**40. Altair charts inside Streamlit.**
Why: Altair ships with Streamlit, gives tooltips and follows the viewer's
light or dark theme, so no extra charting dependency is needed. Static
matplotlib charts remain for the README and findings pages.

**41. Separate, lighter requirements for the app.**
Why: the deployed app only needs Streamlit, pandas and Altair
(`app/requirements.txt`), so it installs quickly and is not tied to the
analysis environment's exact versions. The pipeline uses the pinned
`requirements.txt`.
