"""Bank of England Bank Rate: MPC decision history and the daily rate series.

Two official BoE sources are used:
  * mpcvoting.xlsx - every MPC Bank Rate decision (meeting date and the rate
    decided), including holds. This is where hold decisions come from.
  * IADB series IUDBEDR - the Official Bank Rate on each business day. Used as
    the risk-free rate later and to cross-check every decision.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from . import config

DECISION_COLUMNS = [
    "decision_date", "old_rate_pct", "new_rate_pct", "change_bp", "decision",
    "is_scheduled", "source",
]


def _download(url: str, dest: Path) -> Path:
    resp = requests.get(url, headers=config.HTTP_HEADERS, timeout=60)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def download_voting_history(dest: Path | None = None) -> Path:
    return _download(config.BOE_VOTING_URL, dest or config.RAW_DIR / "boe" / "mpcvoting.xlsx")


def download_bank_rate_daily(dest: Path | None = None) -> Path:
    return _download(config.BOE_IADB_URL, dest or config.RAW_DIR / "boe" / "iudbedr.csv")


def parse_voting_history(path: Path) -> pd.DataFrame:
    """Return one row per MPC meeting: decision_date, new_rate_pct.

    The 'Bank Rate Decisions' sheet has a header block, then meeting dates in
    column B and the Bank Rate decided (as a fraction, 0.0525 = 5.25%) in column C.
    """
    sheet = pd.read_excel(path, sheet_name="Bank Rate Decisions", header=None)
    dates = pd.to_datetime(sheet[1], errors="coerce", format="mixed")
    rates = pd.to_numeric(sheet[2], errors="coerce")
    out = pd.DataFrame({"decision_date": dates, "new_rate_pct": rates * 100})
    out = out.dropna().sort_values("decision_date").reset_index(drop=True)
    out["new_rate_pct"] = out["new_rate_pct"].round(4)
    if out.empty:
        raise ValueError("No decisions parsed from the MPC voting history file")
    return out


def classify_decision(old_rate: float, new_rate: float) -> str:
    """'hike', 'cut' or 'hold' from the rate before and after a meeting."""
    diff = round(new_rate - old_rate, 6)
    if diff > 0:
        return "hike"
    if diff < 0:
        return "cut"
    return "hold"


def build_decisions(meetings: pd.DataFrame, start_date: str = config.START_DATE) -> pd.DataFrame:
    """Add the prior rate, change and decision type, then keep meetings from start_date.

    The old rate for the first kept meeting comes from the meeting before it, so
    we filter only after computing it.
    """
    df = meetings.sort_values("decision_date").reset_index(drop=True).copy()
    df["old_rate_pct"] = df["new_rate_pct"].shift(1)
    df = df[df["decision_date"] >= pd.Timestamp(start_date)].copy()
    if df["old_rate_pct"].isna().any():
        raise ValueError("Need at least one meeting before start_date to know the old rate")
    df["change_bp"] = ((df["new_rate_pct"] - df["old_rate_pct"]) * 100).round(0).astype(int)
    df["decision"] = [classify_decision(o, n) for o, n in zip(df["old_rate_pct"], df["new_rate_pct"])]
    df["decision_date"] = df["decision_date"].dt.strftime("%Y-%m-%d")
    df["is_scheduled"] = (~df["decision_date"].isin(config.UNSCHEDULED_MPC_DATES)).astype(int)
    df["source"] = "Bank of England MPC voting history (mpcvoting.xlsx)"
    return df[DECISION_COLUMNS].reset_index(drop=True)


def parse_bank_rate_daily(path: Path) -> pd.DataFrame:
    """Return date, bank_rate_pct from the IADB CSV export."""
    df = pd.read_csv(path)
    df.columns = [c.strip().upper() for c in df.columns]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["DATE"], format="%d %b %Y").dt.strftime("%Y-%m-%d"),
        "bank_rate_pct": pd.to_numeric(df[config.BOE_BANK_RATE_SERIES], errors="raise"),
    })
    return out.sort_values("date").reset_index(drop=True)


def refresh(offline: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download (unless offline) and parse both BoE sources.

    Writes the decisions reference file to data/reference/. If the download
    fails, falls back to the cached raw files, then to the committed reference
    file for decisions.
    """
    voting_path = config.RAW_DIR / "boe" / "mpcvoting.xlsx"
    daily_path = config.RAW_DIR / "boe" / "iudbedr.csv"
    if not offline:
        try:
            download_voting_history(voting_path)
            download_bank_rate_daily(daily_path)
        except requests.RequestException as exc:
            print(f"  ! BoE download failed ({exc}); using cached files")

    if voting_path.exists():
        decisions = build_decisions(parse_voting_history(voting_path))
        config.BOE_DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        decisions.to_csv(config.BOE_DECISIONS_FILE, index=False)
    else:
        print("  ! No voting history file; using committed decisions reference file")
        decisions = pd.read_csv(config.BOE_DECISIONS_FILE)

    if not daily_path.exists():
        raise FileNotFoundError("Daily Bank Rate (IUDBEDR) not available; run without --offline")
    daily = parse_bank_rate_daily(daily_path)
    return decisions, daily
