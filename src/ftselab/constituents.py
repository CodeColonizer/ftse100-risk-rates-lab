"""FTSE 100 constituents and sectors.

The pipeline reads a dated, committed snapshot from data/reference/. A new
snapshot is only taken on request (run_pipeline.py --refresh-constituents),
because the source page can be edited by anyone and we want each run to be
reproducible.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from . import config

# ICB (Industry Classification Benchmark, 2019 structure): sector -> industry.
# We analyse at industry level (11 groups) because 100 stocks spread over
# ~40 sectors leaves too few stocks per sector for stable statistics.
ICB_SECTOR_TO_INDUSTRY = {
    # Technology
    "Software and Computer Services": "Technology",
    "Technology Hardware and Equipment": "Technology",
    # Telecommunications
    "Telecommunications Service Providers": "Telecommunications",
    "Telecommunications Equipment": "Telecommunications",
    # Health Care
    "Pharmaceuticals, Biotechnology and Marijuana Producers": "Health Care",
    "Medical Equipment and Services": "Health Care",
    "Health Care Providers": "Health Care",
    # Financials
    "Banks": "Financials",
    "Finance and Credit Services": "Financials",
    "Investment Banking and Brokerage Services": "Financials",
    "Closed End Investments": "Financials",
    "Open End and Miscellaneous Investment Vehicles": "Financials",
    "Life Insurance": "Financials",
    "Non-life Insurance": "Financials",
    "Mortgage Real Estate Investment Trusts": "Financials",
    # Real Estate
    "Real Estate Investment Trusts": "Real Estate",
    "Real Estate Investment and Services": "Real Estate",
    # Consumer Discretionary
    "Automobiles and Parts": "Consumer Discretionary",
    "Consumer Services": "Consumer Discretionary",
    "Household Goods and Home Construction": "Consumer Discretionary",
    "Leisure Goods": "Consumer Discretionary",
    "Personal Goods": "Consumer Discretionary",
    "Media": "Consumer Discretionary",
    "Retailers": "Consumer Discretionary",
    "Travel and Leisure": "Consumer Discretionary",
    # Consumer Staples
    "Beverages": "Consumer Staples",
    "Food Producers": "Consumer Staples",
    "Tobacco": "Consumer Staples",
    "Personal Care, Drug and Grocery Stores": "Consumer Staples",
    # Industrials
    "Construction and Materials": "Industrials",
    "Aerospace and Defense": "Industrials",
    "Electronic and Electrical Equipment": "Industrials",
    "General Industrials": "Industrials",
    "Industrial Engineering": "Industrials",
    "Industrial Support Services": "Industrials",
    "Industrial Transportation": "Industrials",
    # Basic Materials
    "Chemicals": "Basic Materials",
    "Industrial Materials": "Basic Materials",
    "Industrial Metals and Mining": "Basic Materials",
    "Precious Metals and Mining": "Basic Materials",
    # Energy
    "Non-Renewable Energy": "Energy",
    "Alternative Energy": "Energy",
    # Utilities
    "Electricity": "Utilities",
    "Gas, Water and Multi-utilities": "Utilities",
    "Waste and Disposal Services": "Utilities",
}

ICB_INDUSTRIES = sorted(set(ICB_SECTOR_TO_INDUSTRY.values()))

SNAPSHOT_COLUMNS = [
    "epic", "yahoo_ticker", "company", "isin", "icb_sector", "icb_industry",
    "is_investment_trust", "snapshot_date", "source_url",
]


def epic_to_yahoo(epic: str) -> str:
    """Convert a London Stock Exchange EPIC code to a Yahoo Finance ticker.

    Yahoo uses a '.L' suffix and replaces dots inside the code with dashes,
    e.g. 'BT.A' -> 'BT-A.L'. A trailing dot (sometimes written, e.g. 'RR.')
    is dropped.
    """
    code = epic.strip().upper().rstrip(".")
    if not code:
        raise ValueError("Empty EPIC code")
    return code.replace(".", "-") + ".L"


def fetch_wikipedia_constituents(url: str = config.WIKIPEDIA_FTSE100_URL) -> pd.DataFrame:
    """Download the constituents table from Wikipedia and return a tidy frame."""
    resp = requests.get(url, headers=config.HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for table in tables:
        cols = [str(c) for c in table.columns]
        if any(c.startswith("Ticker") for c in cols) and any("sector" in c.lower() for c in cols):
            break
    else:
        raise RuntimeError("Could not find the constituents table on the Wikipedia page")

    rename = {}
    for c in table.columns:
        name = str(c).lower()
        if name.startswith("company"):
            rename[c] = "company"
        elif name.startswith("ticker"):
            rename[c] = "epic"
        elif name.startswith("isin"):
            rename[c] = "isin"
        elif "sector" in name:
            rename[c] = "icb_sector"
    return table.rename(columns=rename)[["company", "epic", "isin", "icb_sector"]]


def build_snapshot(raw: pd.DataFrame, snapshot_date: str, source_url: str) -> pd.DataFrame:
    """Standardise a raw constituents table into the committed snapshot format."""
    df = raw.copy()
    for col in ["company", "epic", "isin", "icb_sector"]:
        df[col] = df[col].astype(str).str.strip()
    unknown = sorted(set(df["icb_sector"]) - set(ICB_SECTOR_TO_INDUSTRY))
    if unknown:
        raise ValueError(f"ICB sectors without an industry mapping: {unknown}")
    df["yahoo_ticker"] = df["epic"].map(epic_to_yahoo)
    df["icb_industry"] = df["icb_sector"].map(ICB_SECTOR_TO_INDUSTRY)
    df["is_investment_trust"] = (df["icb_sector"] == "Closed End Investments").astype(int)
    df["snapshot_date"] = snapshot_date
    df["source_url"] = source_url
    return df[SNAPSHOT_COLUMNS].sort_values("epic").reset_index(drop=True)


def snapshot_path(snapshot_date: str) -> Path:
    return config.REFERENCE_DIR / f"ftse100_constituents_{snapshot_date}.csv"


def refresh_snapshot(snapshot_date: str | None = None) -> Path:
    """Take a new dated snapshot from Wikipedia and save it to data/reference/."""
    snapshot_date = snapshot_date or date.today().isoformat()
    raw = fetch_wikipedia_constituents()
    snap = build_snapshot(raw, snapshot_date, config.WIKIPEDIA_FTSE100_URL)
    path = snapshot_path(snapshot_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    snap.to_csv(path, index=False)
    return path


def latest_snapshot_path() -> Path:
    files = sorted(config.REFERENCE_DIR.glob("ftse100_constituents_*.csv"))
    if not files:
        raise FileNotFoundError(
            "No constituents snapshot found. Run: python run_pipeline.py --refresh-constituents"
        )
    return files[-1]


def load_snapshot(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or latest_snapshot_path(), dtype=str)
