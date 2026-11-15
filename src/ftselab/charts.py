"""Phase 1 charts: data coverage and the Bank Rate path."""
from __future__ import annotations

import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import config  # noqa: E402

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 150, "font.size": 11,
    "axes.titlesize": 14, "axes.titleweight": "bold", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3,
})

HIKE, CUT, HOLD, LINE = "#c0392b", "#1e8449", "#95a5a6", "#1f4e79"


def coverage_chart(conn: sqlite3.Connection) -> str:
    """How many of today's constituents have a price on each trading day."""
    df = pd.read_sql_query(
        "SELECT p.date, COUNT(*) n FROM clean_prices p "
        "JOIN clean_constituents c ON c.ticker = p.ticker GROUP BY p.date ORDER BY p.date", conn)
    total = pd.read_sql_query("SELECT COUNT(*) n FROM clean_constituents", conn)["n"].iloc[0]
    df["date"] = pd.to_datetime(df["date"])

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(df["date"], df["n"], color=LINE, lw=2)
    ax.axhline(total, color="grey", ls="--", lw=1)
    ax.text(df["date"].iloc[0], total + 1.5, f"All {total} current constituents", color="grey")
    ax.set_ylim(0, total + 10)
    ax.set_title("Price history coverage: today's FTSE 100 members with data on each day")
    ax.set_ylabel("Number of stocks with a price")
    ax.set_xlabel("")
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.01, 0.01, "Stocks that listed after 2010 join the line later. Firms that left the "
             "index or delisted are not included (survivorship bias). Source: Yahoo Finance.",
             fontsize=9, color="dimgrey")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = config.FIGURES_DIR / "phase1_price_coverage.png"
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def bank_rate_chart(conn: sqlite3.Connection) -> str:
    """Bank Rate since 2010 with each MPC decision marked."""
    rate = pd.read_sql_query("SELECT date, bank_rate_pct FROM clean_bank_rate_daily", conn)
    dec = pd.read_sql_query("SELECT decision_date, new_rate_pct, decision FROM clean_boe_decisions", conn)
    rate["date"] = pd.to_datetime(rate["date"])
    dec["decision_date"] = pd.to_datetime(dec["decision_date"])

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.step(rate["date"], rate["bank_rate_pct"], where="post", color=LINE, lw=2, label="Bank Rate")
    styles = {"hold": (HOLD, "o", 18), "hike": (HIKE, "^", 70), "cut": (CUT, "v", 70)}
    for kind, (colour, marker, size) in styles.items():
        d = dec[dec["decision"] == kind]
        ax.scatter(d["decision_date"], d["new_rate_pct"], color=colour, marker=marker, s=size,
                   zorder=3, label=f"{kind.capitalize()} ({len(d)})")
    notes = [("Covid emergency cuts\n(March 2020)", "2020-03-19", 0.25, "2018-01-01", 1.6),
             ("Mini-budget\n(September 2022)", "2022-09-22", 2.25, "2019-09-01", 3.2)]
    for label, when, y, text_when, text_y in notes:
        ax.annotate(label, (pd.Timestamp(when), y), xytext=(pd.Timestamp(text_when), text_y),
                    ha="center", fontsize=9, arrowprops={"arrowstyle": "->", "color": "grey"})
    ax.set_title("Bank of England Bank Rate and MPC decisions since 2010")
    ax.set_ylabel("Bank Rate (%)")
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(loc="upper left", frameon=False)
    fig.text(0.01, 0.01, "Source: Bank of England (MPC voting history; series IUDBEDR).",
             fontsize=9, color="dimgrey")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = config.FIGURES_DIR / "phase1_bank_rate_decisions.png"
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def make_all(conn: sqlite3.Connection) -> list[str]:
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return [coverage_chart(conn), bank_rate_chart(conn)]
