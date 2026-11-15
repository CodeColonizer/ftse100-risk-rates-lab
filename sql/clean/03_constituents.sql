-- One row per current constituent with its sector, quote currency and price
-- coverage. n_missing_days counts index trading days between a stock's first
-- and last price with no price for that stock.
DROP TABLE IF EXISTS clean_constituents;

CREATE TABLE clean_constituents AS
WITH coverage AS (
    SELECT ticker,
           MIN(date)   AS first_price_date,
           MAX(date)   AS last_price_date,
           COUNT(*)    AS n_price_days
    FROM clean_prices
    GROUP BY ticker
)
SELECT c.epic,
       c.yahoo_ticker                       AS ticker,
       c.company,
       c.isin,
       c.icb_sector,
       c.icb_industry,
       CAST(c.is_investment_trust AS INTEGER) AS is_investment_trust,
       c.snapshot_date,
       i.currency,
       v.first_price_date,
       v.last_price_date,
       COALESCE(v.n_price_days, 0)          AS n_price_days,
       (SELECT COUNT(*) FROM clean_trading_calendar t
         WHERE t.date BETWEEN v.first_price_date AND v.last_price_date)
         - COALESCE(v.n_price_days, 0)      AS n_missing_days
FROM raw_constituents c
LEFT JOIN raw_ticker_info i ON i.ticker = c.yahoo_ticker
LEFT JOIN coverage v        ON v.ticker = c.yahoo_ticker
ORDER BY c.epic;
