"""Phase 2 charts. Static PNGs for the README and findings.

Colour use: one blue hue for magnitudes; a red-grey-blue diverging scale for
values that can be negative or positive (red = loss); grey for reference
lines such as the FTSE 100 index. Eleven sectors are never given eleven
colours: they are labelled directly or shown as small multiples.
"""
from __future__ import annotations

import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

from . import config  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, BLUE_DARK, RED, NEUTRAL, REF = "#2a78d6", "#184f95", "#e34948", "#f0efec", "#8a8984"
SEQ = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
DIV = LinearSegmentedColormap.from_list("red_grey_blue", [RED, "#f1a3a2", NEUTRAL, "#86b6ef", BLUE_DARK])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "figure.dpi": 110, "savefig.dpi": 150, "font.size": 10.5,
    "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": "#c3c2b7", "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
})

INDEX_NAME = "FTSE 100 index (price)"
EXTRA = ["All stocks (equal weight)", "Financials excl. investment trusts"]


def _footer(fig, text):
    fig.text(0.01, 0.01, text, fontsize=8.5, color=INK_2)


def _save(fig, name):
    path = config.FIGURES_DIR / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def sector_risk_chart(conn: sqlite3.Connection) -> str:
    s = pd.read_sql_query("SELECT * FROM mart_sector_risk", conn)
    s = s[~s["sector"].isin(EXTRA)].sort_values("ann_volatility")
    colours = [REF if n == INDEX_NAME else BLUE for n in s["sector"]]
    labels = ["FTSE 100 index" if n == INDEX_NAME else n for n in s["sector"]]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True)
    a1.barh(labels, s["ann_volatility"] * 100, color=colours, height=0.65)
    a1.set_title("Annualised volatility (%)", fontsize=11.5)
    a2.barh(labels, s["max_drawdown"] * 100, color=colours, height=0.65)
    a2.set_title("Worst peak-to-trough fall (%)", fontsize=11.5)
    for ax, col in [(a1, "ann_volatility"), (a2, "max_drawdown")]:
        ax.grid(axis="y", visible=False)
        for y, v in enumerate(s[col] * 100):
            ax.text(v + (0.4 if v >= 0 else -0.8), y, f"{v:.0f}", va="center",
                    ha="left" if v >= 0 else "right", fontsize=9, color=INK_2)
    a2.set_xlim((s["max_drawdown"].min() * 100) * 1.18, 0)
    fig.suptitle("Sector risk, January 2010 to November 2026: Basic Materials and Energy "
                 "were the riskiest; Consumer Staples the steadiest", fontsize=13, fontweight="bold", x=0.01,
                 ha="left")
    _footer(fig, "Equal-weighted portfolios of today's FTSE 100 members in each ICB industry, "
                 "rebalanced daily; dividends included. Grey = FTSE 100 price index. Source: Yahoo Finance.")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return _save(fig, "phase2_sector_risk.png")


def correlation_heatmap(conn: sqlite3.Connection) -> str:
    c = pd.read_sql_query("SELECT * FROM mart_sector_correlation", conn)
    wide = c.pivot(index="sector_a", columns="sector_b", values="correlation")
    order = wide.mean().sort_values().index  # least correlated first
    wide = wide.loc[order, order]
    n = len(wide)

    fig, ax = plt.subplots(figsize=(10, 8.4))
    masked = wide.where(~np.eye(n, dtype=bool))
    im = ax.imshow(masked, cmap=SEQ, vmin=0.2, vmax=0.9)
    ax.set_xticks(range(n), wide.columns, rotation=40, ha="right")
    ax.set_yticks(range(n), wide.index)
    ax.grid(False)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            v = wide.iat[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.5,
                    color="white" if v > 0.62 else INK)
    cb = fig.colorbar(im, ax=ax, shrink=0.75)
    cb.set_label("Correlation of daily returns")
    ax.set_title("Sector correlations: Energy, Basic Materials and Utilities move least "
                 "with the rest", loc="left")
    _footer(fig, "Daily returns, Jan 2010 to Nov 2026. Sorted from least to most correlated on "
                 "average. 1 = always move together; 0 = unrelated. Source: Yahoo Finance.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, "phase2_sector_correlation.png")


def rolling_correlation_chart(conn: sqlite3.Connection) -> str:
    r = pd.read_sql_query("SELECT * FROM mart_rolling_sector_corr", conn)
    r["date"] = pd.to_datetime(r["date"])
    wide = r.pivot(index="date", columns="sector", values="corr_with_index")
    median = wide.median(axis=1)
    order = wide.mean().sort_values().index

    fig, axes = plt.subplots(3, 4, figsize=(13, 8.2), sharex=True, sharey=True)
    for ax, sector in zip(axes.flat, order):
        for p in config.STRESS_PERIODS:
            ax.axvspan(pd.Timestamp(p["base_date"]), pd.Timestamp(p["end_date"]),
                       color=RED, alpha=0.12, lw=0)
        ax.plot(median.index, median, color=REF, lw=1.2)
        ax.plot(wide.index, wide[sector], color=BLUE, lw=1.8)
        ax.set_title(sector, fontsize=10.5, loc="left")
        ax.set_ylim(0, 1)
        ax.xaxis.set_major_locator(mdates.YearLocator(4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    key = axes.flat[-1]
    key.axis("off")
    key.plot([0.05, 0.25], [0.75, 0.75], color=BLUE, lw=1.8, transform=key.transAxes)
    key.text(0.3, 0.75, "This sector", va="center", transform=key.transAxes)
    key.plot([0.05, 0.25], [0.55, 0.55], color=REF, lw=1.2, transform=key.transAxes)
    key.text(0.3, 0.55, "Median of all sectors", va="center", transform=key.transAxes)
    key.add_patch(plt.Rectangle((0.05, 0.3), 0.2, 0.1, color=RED, alpha=0.12, transform=key.transAxes))
    key.text(0.3, 0.35, "Stress periods", va="center", transform=key.transAxes)
    for ax in axes[:, 0]:
        ax.set_ylabel("Correlation")
    fig.suptitle("One-year rolling correlation with the FTSE 100: diversification is not "
                 "stable over time", fontsize=13, fontweight="bold", x=0.01, ha="left")
    _footer(fig, "Correlation of each equal-weighted sector's daily returns with the FTSE 100 index "
                 "over the previous 252 trading days. Source: Yahoo Finance.")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    return _save(fig, "phase2_rolling_correlation.png")


def stress_heatmap(conn: sqlite3.Connection) -> str:
    st = pd.read_sql_query("SELECT * FROM mart_stress_periods WHERE kind IN ('sector', 'index')", conn)
    st["name"] = st["name"].replace({config.INDEX_TICKER: "FTSE 100 index"})
    wide = st.pivot(index="name", columns="period", values="window_return")
    cols = [p["period"] for p in config.STRESS_PERIODS]
    labels = {p["period"]: f"{p['label']}\n{pd.Timestamp(p['base_date']):%d %b %Y} to "
                          f"{pd.Timestamp(p['end_date']):%d %b %Y}" for p in config.STRESS_PERIODS}
    refs = ["FTSE 100 index", "All stocks (equal weight)"]
    body = wide.drop(index=refs).sort_values("hikes_2022", ascending=False)
    wide = pd.concat([body, wide.loc[refs]])[cols] * 100

    fig, ax = plt.subplots(figsize=(10, 7.8))
    lim = np.nanmax(np.abs(wide.values))
    ax.imshow(wide.values, cmap=DIV, norm=TwoSlopeNorm(0, -lim, lim), aspect="auto")
    ax.set_xticks(range(len(cols)), [labels[c] for c in cols])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(wide)), wide.index)
    ax.grid(False)
    ax.axhline(len(body) - 0.5, color=INK, lw=1.2)
    for i in range(wide.shape[0]):
        for j in range(wide.shape[1]):
            v = wide.iat[i, j]
            ax.text(j, i, f"{v:+.1f}%", ha="center", va="center", fontsize=9.5,
                    color="white" if abs(v) > lim * 0.8 else INK)
    ax.set_title("Sector returns in three stress periods: in 2022 Energy gained 35% while "
                 "Real Estate lost 36%", loc="left", pad=48)
    _footer(fig, "Close on the first date to close on the last date; equal-weighted sectors, "
                 "dividends included (the index excludes them). Sorted by 2022. Source: Yahoo Finance.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, "phase2_stress_periods.png")


def diversification_map(conn: sqlite3.Connection) -> str:
    s = pd.read_sql_query("SELECT * FROM mart_sector_risk", conn)
    s = s[~s["sector"].isin(EXTRA + [INDEX_NAME])]
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.axvline(1, color=REF, lw=1, ls="--")
    ax.text(1.005, s["corr_with_index"].min() - 0.015, "Beta = 1:\nmoves with the market",
            fontsize=8.5, color=INK_2, va="top")
    ax.scatter(s["beta"], s["corr_with_index"], s=90, color=BLUE, edgecolor=SURFACE,
               linewidth=2, zorder=3)
    offsets = {"Utilities": (8, -4), "Health Care": (8, 4), "Technology": (8, -10),
               "Real Estate": (8, 4), "Telecommunications": (-10, 8), "Energy": (8, -10),
               "Basic Materials": (-8, 8), "Consumer Staples": (8, -4)}
    for _, row in s.iterrows():
        dx, dy = offsets.get(row["sector"], (8, 0))
        ax.annotate(row["sector"], (row["beta"], row["corr_with_index"]), xytext=(dx, dy),
                    textcoords="offset points", fontsize=9.5,
                    ha="left" if dx > 0 else "right", va="center")
    ax.set_xlabel("Beta to the FTSE 100 (how much the sector moves per 1% index move)")
    ax.set_ylabel("Correlation with the FTSE 100")
    ax.set_title("Which sectors diversify? Lower and further left = more diversifying",
                 loc="left")
    pad = 0.06
    ax.set_xlim(s["beta"].min() - 0.1, s["beta"].max() + 0.15)
    ax.set_ylim(s["corr_with_index"].min() - pad, s["corr_with_index"].max() + pad)
    _footer(fig, "Daily returns, Jan 2010 to Nov 2026; equal-weighted sectors of today's members. "
                 "Source: Yahoo Finance.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, "phase2_diversification_map.png")


def make_all(conn: sqlite3.Connection) -> list[str]:
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return [sector_risk_chart(conn), correlation_heatmap(conn), rolling_correlation_chart(conn),
            stress_heatmap(conn), diversification_map(conn)]
