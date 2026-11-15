-- Clean daily prices.
--   1. Keep one row per ticker and day (latest download wins).
--   2. Apply documented corrections from data/reference/price_corrections.csv
--      (unadjusted splits, unusable history before a listing date).
--   3. Convert lines Yahoo quotes in USD or EUR into pence at that day's
--      exchange rate, so every return is from a sterling investor's view.
--   4. Keep only index trading days and positive prices.
--   5. Flag suspicious rows using the day-on-day adjusted price ratio:
--        is_unit_spike   one-day jump of ~100x that reverses the next day
--                        (Yahoo pence/pound glitch) -> removed
--        is_bad_print    "flat bar" (open = high = low = close) with a large move
--                        that reverses the next day -> removed
--        is_unit_shift   ~100x jump that does NOT reverse -> kept, fails a test
--        is_extreme_move other move beyond the extreme threshold -> kept, reported
--        is_stale        zero volume and unchanged close -> kept, reported,
--                        unless many stocks are stale on the same day
--                        (is_carried_forward) -> removed
--   Gaps are NOT forward-filled: a missing day stays missing.
-- Upper-case tokens in double braces are replaced with thresholds from
-- src/ftselab/config.py before this file runs.

DROP TABLE IF EXISTS clean_prices_flagged;

CREATE TABLE clean_prices_flagged AS
WITH dedup AS (
    SELECT r.*,
           ROW_NUMBER() OVER (PARTITION BY ticker, date ORDER BY downloaded_at DESC) AS rn
    FROM raw_prices r
),
corrected AS (
    SELECT d.ticker, d.date,
           COALESCE(s.factor, 1.0) AS split_factor,
           d.open, d.high, d.low, d.close, d.adj_close, d.volume,
           CASE WHEN s.ticker IS NOT NULL OR x.ticker IS NOT NULL THEN 1 ELSE 0 END AS was_corrected,
           CASE WHEN x.ticker IS NOT NULL THEN 1 ELSE 0 END AS before_usable_history
    FROM dedup d
    LEFT JOIN raw_price_corrections s
           ON s.ticker = d.ticker AND s.action = 'scale_before' AND d.date < s.before_date
    LEFT JOIN raw_price_corrections x
           ON x.ticker = d.ticker AND x.action = 'drop_before' AND d.date < x.before_date
    WHERE d.rn = 1
),
in_pence AS (
    SELECT c.ticker, c.date,
           CASE WHEN c.ticker = '^FTSE' THEN 'index points'
                ELSE COALESCE(i.currency, 'GBp') END AS quote_currency,
           -- pence per unit of the quote currency (1 for GBp)
           CASE COALESCE(i.currency, 'GBp')
                WHEN 'GBp' THEN 1.0
                WHEN 'GBP' THEN 100.0
                ELSE 100.0 / (SELECT f.rate FROM raw_fx f
                               WHERE f.pair = 'GBP' || i.currency || '=X' AND f.date <= c.date
                               ORDER BY f.date DESC LIMIT 1)
           END * c.split_factor AS mult,
           c.open, c.high, c.low, c.close, c.adj_close, c.volume,
           c.split_factor, c.was_corrected, c.before_usable_history
    FROM corrected c
    LEFT JOIN raw_ticker_info i ON i.ticker = c.ticker AND c.ticker <> '^FTSE'
),
valid AS (
    SELECT p.ticker, p.date, p.quote_currency,
           p.open * p.mult AS open, p.high * p.mult AS high, p.low * p.mult AS low,
           p.close * p.mult AS close, p.adj_close * p.mult AS adj_close,
           p.volume / p.split_factor AS volume,
           p.was_corrected, p.before_usable_history
    FROM in_pence p
    JOIN clean_trading_calendar t ON t.date = p.date
    WHERE p.adj_close IS NOT NULL AND p.adj_close > 0
      AND p.close IS NOT NULL AND p.close > 0
      AND p.mult IS NOT NULL
),
ratios AS (
    SELECT v.*,
           v.adj_close / LAG(v.adj_close) OVER w AS prev_ratio,
           LEAD(v.adj_close) OVER w / v.adj_close AS next_ratio,
           LAG(v.close) OVER w AS prev_close
    FROM valid v
    WHERE v.before_usable_history = 0
    WINDOW w AS (PARTITION BY ticker ORDER BY date)
),
spikes AS (
    SELECT r.*,
           CASE WHEN (prev_ratio > {{UNIT_RATIO_HIGH}} AND next_ratio < {{UNIT_RATIO_LOW}})
                  OR (prev_ratio < {{UNIT_RATIO_LOW}} AND next_ratio > {{UNIT_RATIO_HIGH}})
                THEN 1 ELSE 0 END AS is_unit_spike,
           CASE WHEN open = high AND high = low AND low = close
                 AND ABS(prev_ratio - 1) > {{BAD_PRINT_MOVE}}
                 AND ABS(prev_ratio * next_ratio - 1) < {{BAD_PRINT_REVERSAL}}
                THEN 1 ELSE 0 END AS is_bad_print
    FROM ratios r
),
spikes_with_lag AS (
    SELECT s.*,
           COALESCE(LAG(is_unit_spike + is_bad_print) OVER (PARTITION BY ticker ORDER BY date), 0)
               AS follows_spike
    FROM spikes s
),
flagged AS (
    SELECT ticker, date, quote_currency, open, high, low, close, adj_close, volume,
           prev_ratio, was_corrected,
           is_unit_spike,
           CASE WHEN is_unit_spike = 0 THEN is_bad_print ELSE 0 END AS is_bad_print,
           CASE WHEN is_unit_spike = 0 AND follows_spike = 0
                     AND (prev_ratio > {{UNIT_RATIO_HIGH}} OR prev_ratio < {{UNIT_RATIO_LOW}})
                THEN 1 ELSE 0 END AS is_unit_shift,
           CASE WHEN is_unit_spike = 0 AND is_bad_print = 0 AND follows_spike = 0
                     AND prev_ratio BETWEEN {{UNIT_RATIO_LOW}} AND {{UNIT_RATIO_HIGH}}
                     AND ABS(prev_ratio - 1) > {{EXTREME_MOVE}}
                THEN 1 ELSE 0 END AS is_extreme_move,
           CASE WHEN ticker <> '^FTSE' AND volume = 0 AND close = prev_close
                THEN 1 ELSE 0 END AS is_stale
    FROM spikes_with_lag
)
-- is_carried_forward: a stale row on a day when many stocks are stale at once.
-- That pattern means the source repeated yesterday's close for a day it has
-- no data for, which would create false 0% returns -> removed.
SELECT f.*,
       CASE WHEN is_stale = 1
                 AND SUM(is_stale) OVER (PARTITION BY date) >= {{STALE_DAY_MIN_STOCKS}}
            THEN 1 ELSE 0 END AS is_carried_forward
FROM flagged f;

-- Audit trail: every row removed from the clean layer, with the reason.
DROP TABLE IF EXISTS clean_price_exclusions;
CREATE TABLE clean_price_exclusions AS
SELECT ticker, date, close, adj_close, prev_ratio,
       CASE WHEN is_unit_spike = 1 THEN 'one-day ~100x unit spike that reverses next day'
            WHEN is_bad_print = 1
            THEN 'flat-bar bad print: large move with open = high = low = close, reversed next day'
            ELSE 'carried-forward price: zero volume and unchanged close on a day many stocks show the same'
       END AS reason
FROM clean_prices_flagged
WHERE is_unit_spike = 1 OR is_bad_print = 1 OR is_carried_forward = 1
UNION ALL
SELECT d.ticker, d.date, d.close, d.adj_close, NULL,
       'before usable history (see price_corrections.csv): ' || x.reason
FROM raw_prices d
JOIN raw_price_corrections x
  ON x.ticker = d.ticker AND x.action = 'drop_before' AND d.date < x.before_date
WHERE d.date IN (SELECT date FROM clean_trading_calendar)
ORDER BY ticker, date;

DROP TABLE IF EXISTS clean_prices;
CREATE TABLE clean_prices AS
SELECT ticker, date, quote_currency, open, high, low, close, adj_close, volume,
       was_corrected, is_unit_shift, is_extreme_move, is_stale
FROM clean_prices_flagged
WHERE is_unit_spike = 0 AND is_bad_print = 0 AND is_carried_forward = 0
ORDER BY ticker, date;

CREATE UNIQUE INDEX ix_clean_prices_ticker_date ON clean_prices (ticker, date);
CREATE INDEX ix_clean_prices_date ON clean_prices (date);
