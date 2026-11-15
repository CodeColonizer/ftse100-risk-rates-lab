-- London Stock Exchange trading days, taken from the days the FTSE 100 index
-- has a valid level. Every other table is aligned to this calendar.
DROP TABLE IF EXISTS clean_trading_calendar;

CREATE TABLE clean_trading_calendar AS
SELECT DISTINCT date
FROM raw_prices
WHERE ticker = '^FTSE'
  AND adj_close IS NOT NULL
  AND adj_close > 0
  AND CAST(strftime('%w', date) AS INTEGER) BETWEEN 1 AND 5   -- Monday to Friday
ORDER BY date;

CREATE UNIQUE INDEX ix_clean_trading_calendar_date ON clean_trading_calendar (date);
