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

**7. Adjusted close for returns; both close and adjusted close kept.**
Why: adjusted close includes dividends and splits, so returns reflect what a
shareholder earned. The FTSE 100 index (`^FTSE`) is a price index without
dividends, which slightly understates the market's return when we calculate
beta and excess returns. Noted as a limitation; a total-return index is not
freely available.

**8. Lines quoted in USD or EUR are converted to pence.**
Why: Yahoo serves Compass and InterContinental Hotels in US dollars (for the
whole history) and Metlen in euros. For a sterling investor, a return should
include the currency effect, and the benchmark index is in sterling. We
convert at the latest daily GBP/USD or GBP/EUR rate on or before each day.

**9. No forward-filling of missing prices.**
Why: filling a gap with yesterday's price invents a 0% return, which
understates volatility and distorts correlations. Missing days stay missing
and are counted (26 across all stocks).

**10. Remove a price only for a clear, documented reason; otherwise flag it.**
- *Removed*: (a) one-day ~100x jumps that reverse (pence/pound glitches; none
  found this run), (b) "flat-bar" bad prints: open = high = low = close, a move
  over 15%, and the next day back within 5% (5 rows, all in early 2010),
  (c) history before a documented usable date (see 11).
- *Flagged and kept*: one-day moves over 25% (24 rows, mostly genuine, e.g.
  Covid crash, vaccine news on 9 Nov 2020), zero-volume unchanged days.
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
