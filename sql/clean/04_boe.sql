-- Bank Rate decisions and the daily Bank Rate, aligned to trading days.

-- Decisions: event_date is the first trading day on or after the announcement.
-- MPC decisions are announced at 12:00 UK time, so that day's close already
-- reflects the news. iudbedr_rate_pct is the official daily series on the
-- decision date, used to cross-check every decision.
DROP TABLE IF EXISTS clean_boe_decisions;

CREATE TABLE clean_boe_decisions AS
SELECT d.decision_date,
       (SELECT MIN(t.date) FROM clean_trading_calendar t
         WHERE t.date >= d.decision_date)            AS event_date,
       CAST(d.old_rate_pct AS REAL)                   AS old_rate_pct,
       CAST(d.new_rate_pct AS REAL)                   AS new_rate_pct,
       CAST(d.change_bp AS INTEGER)                   AS change_bp,
       d.decision,
       CAST(d.is_scheduled AS INTEGER)                AS is_scheduled,
       (SELECT r.bank_rate_pct FROM raw_bank_rate_daily r
         WHERE r.date <= d.decision_date
         ORDER BY r.date DESC LIMIT 1)                AS iudbedr_rate_pct
FROM raw_boe_decisions d
ORDER BY d.decision_date;

-- Daily Bank Rate on each trading day: the latest published value on or before
-- that day (the series is not published on UK bank holidays).
DROP TABLE IF EXISTS clean_bank_rate_daily;

CREATE TABLE clean_bank_rate_daily AS
SELECT t.date,
       (SELECT r.bank_rate_pct FROM raw_bank_rate_daily r
         WHERE r.date <= t.date
         ORDER BY r.date DESC LIMIT 1) AS bank_rate_pct
FROM clean_trading_calendar t
ORDER BY t.date;

CREATE UNIQUE INDEX ix_clean_bank_rate_daily_date ON clean_bank_rate_daily (date);
