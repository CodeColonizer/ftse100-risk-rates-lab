"""Daily price download from Yahoo Finance (via yfinance).

Prices are stored exactly as Yahoo returns them (raw layer). Both the close
and the adjusted close are kept: the adjusted close accounts for dividends
and splits and is what returns will be calculated from.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from . import config

RAW_PRICE_FILE = config.RAW_DIR / "prices" / "prices_raw.csv.gz"
RAW_INFO_FILE = config.RAW_DIR / "prices" / "ticker_info.csv"
RAW_FX_FILE = config.RAW_DIR / "prices" / "fx_raw.csv"
PRICE_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]


def _to_long(frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Turn yfinance's wide (ticker, field) columns into one row per ticker-day."""
    parts = []
    for t in tickers:
        if t not in frame.columns.get_level_values(0):
            continue
        sub = frame[t].copy()
        sub.columns = [str(c).lower().replace(" ", "_") for c in sub.columns]
        sub = sub.dropna(how="all")
        if sub.empty:
            continue
        sub["ticker"] = t
        sub["date"] = pd.to_datetime(sub.index).strftime("%Y-%m-%d")
        parts.append(sub)
    if not parts:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    for col in PRICE_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    return out[PRICE_COLUMNS]


def download_prices(
    tickers: list[str],
    start: str = config.START_DATE,
    batch_size: int = 20,
    retries: int = 3,
    pause: float = 2.0,
) -> pd.DataFrame:
    """Download daily OHLCV and adjusted close for tickers, in small batches.

    Batches and retries keep us within Yahoo's informal rate limits. Tickers
    that still return nothing are reported, not silently dropped.
    """
    frames, missing = [], []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        got = pd.DataFrame(columns=PRICE_COLUMNS)
        todo = list(batch)
        for attempt in range(1, retries + 1):
            wide = yf.download(
                todo, start=start, auto_adjust=False, actions=False,
                group_by="ticker", threads=True, progress=False,
            )
            part = _to_long(wide, todo) if not wide.empty else pd.DataFrame(columns=PRICE_COLUMNS)
            got = pd.concat([got, part], ignore_index=True) if not got.empty else part
            todo = [t for t in todo if t not in set(got["ticker"])]
            if not todo:
                break
            time.sleep(pause * attempt)
        missing.extend(todo)
        frames.append(got)
        print(f"  prices: {min(i + batch_size, len(tickers))}/{len(tickers)} tickers requested")
        time.sleep(pause)
    if missing:
        print(f"  ! No price data returned for: {', '.join(missing)}")
    prices = pd.concat(frames, ignore_index=True)
    prices["downloaded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return prices


def download_ticker_info(tickers: list[str]) -> pd.DataFrame:
    """Quote currency and exchange for each ticker (GBp = pence, GBP = pounds)."""
    rows = []
    for t in tickers:
        currency = exchange = None
        try:
            fi = yf.Ticker(t).fast_info
            currency, exchange = fi.get("currency"), fi.get("exchange")
        except Exception as exc:  # network or Yahoo error: record and move on
            print(f"  ! Could not read info for {t}: {exc}")
        rows.append({"ticker": t, "currency": currency, "exchange": exchange})
    return pd.DataFrame(rows)


def download_fx(pairs: list[str] = config.FX_PAIRS) -> pd.DataFrame:
    """Daily exchange rates (foreign currency per pound) as pair, date, rate."""
    fx = download_prices(pairs, start=config.START_DATE)
    return fx.rename(columns={"ticker": "pair", "close": "rate"})[["pair", "date", "rate"]].dropna()


def refresh(tickers: list[str], offline: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download prices, ticker info and FX (unless offline), cached in data/raw/."""
    if offline:
        if not (RAW_PRICE_FILE.exists() and RAW_FX_FILE.exists()):
            raise FileNotFoundError("No cached prices; run without --offline first")
        info = pd.read_csv(RAW_INFO_FILE) if RAW_INFO_FILE.exists() else pd.DataFrame(
            columns=["ticker", "currency", "exchange"])
        return pd.read_csv(RAW_PRICE_FILE), info, pd.read_csv(RAW_FX_FILE)

    prices = download_prices(tickers)
    info = download_ticker_info(tickers)
    fx = download_fx()
    RAW_PRICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(RAW_PRICE_FILE, index=False)
    info.to_csv(RAW_INFO_FILE, index=False)
    fx.to_csv(RAW_FX_FILE, index=False)
    return prices, info, fx
