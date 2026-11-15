-- Total returns built from the close price and dividends.
--
-- Why: Yahoo's "adjusted close" for London stocks barely reflects dividends
-- (HSBC's adjusted and raw close differ by under 1% over 16 years), but its
-- dividend records are correct. So we build total returns ourselves:
--   total return on day t = (close_t + dividend going ex on day t) / close_(t-1) - 1
-- Only calculated when the stock also has a price on the previous trading day
-- (no bridging of gaps). The FTSE 100 index has no dividends: its total return
-- equals its price return.

-- Dividends converted to the same units as clean_prices (pence), using that
-- day's clean/raw close ratio, which carries any FX conversion and documented
-- split correction applied to the price.
DROP TABLE IF EXISTS clean_dividends;
CREATE TABLE clean_dividends AS
WITH raw_close AS (
    SELECT ticker, date, close
    FROM (SELECT ticker, date, close,
                 ROW_NUMBER() OVER (PARTITION BY ticker, date ORDER BY downloaded_at DESC) AS rn
          FROM raw_prices)
    WHERE rn = 1
),
divs AS (
    -- documented dividend fixes (action scale_dividends_before in price_corrections.csv)
    SELECT r.ticker, r.date,
           SUM(r.dividend * COALESCE(k.factor, 1.0)) AS dividend,
           MAX(CASE WHEN k.ticker IS NOT NULL THEN 1 ELSE 0 END) AS was_corrected
    FROM raw_dividends r
    LEFT JOIN raw_price_corrections k
           ON k.ticker = r.ticker AND k.action = 'scale_dividends_before' AND r.date < k.before_date
    WHERE r.dividend > 0
    GROUP BY r.ticker, r.date
),
span AS (
    SELECT ticker, MIN(date) AS first_date, MAX(date) AS last_date FROM clean_prices GROUP BY ticker
)
SELECT d.ticker,
       d.date                                     AS ex_date,
       d.dividend                                 AS dividend_quote_currency,
       d.dividend * p.close / r.close             AS dividend_pence,
       d.dividend * p.close / r.close / prev.close AS dividend_yield_on_day,
       d.was_corrected,
       CASE WHEN p.ticker IS NOT NULL THEN 1 ELSE 0 END AS matched_to_price,
       CASE WHEN d.date BETWEEN s.first_date AND s.last_date THEN 1 ELSE 0 END AS within_price_history
FROM divs d
LEFT JOIN clean_prices p ON p.ticker = d.ticker AND p.date = d.date
LEFT JOIN raw_close r    ON r.ticker = d.ticker AND r.date = d.date
LEFT JOIN span s         ON s.ticker = d.ticker
LEFT JOIN clean_prices prev
       ON prev.ticker = d.ticker
      AND prev.date = (SELECT MAX(x.date) FROM clean_prices x
                       WHERE x.ticker = d.ticker AND x.date < d.date)
ORDER BY d.ticker, d.date;

DROP TABLE IF EXISTS clean_total_returns;
CREATE TABLE clean_total_returns AS
WITH cal AS (
    SELECT date, ROW_NUMBER() OVER (ORDER BY date) AS n FROM clean_trading_calendar
),
p AS (
    SELECT p.ticker, p.date, p.close, c.n,
           LAG(p.close) OVER w AS prev_close,
           LAG(c.n)     OVER w AS prev_n
    FROM clean_prices p
    JOIN cal c ON c.date = p.date
    WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
)
SELECT p.ticker, p.date,
       COALESCE(d.dividend_pence, 0) AS dividend,
       CASE WHEN p.prev_n = p.n - 1 THEN p.close / p.prev_close - 1 END AS price_return,
       CASE WHEN p.prev_n = p.n - 1
            THEN (p.close + COALESCE(d.dividend_pence, 0)) / p.prev_close - 1 END AS total_return
FROM p
LEFT JOIN clean_dividends d ON d.ticker = p.ticker AND d.ex_date = p.date
ORDER BY p.ticker, p.date;

CREATE UNIQUE INDEX ix_clean_total_returns ON clean_total_returns (ticker, date);
