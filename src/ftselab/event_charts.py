"""Phase 3 charts: market reaction, sector volatility, sector direction, placebo."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

from . import config
from .risk_charts import BLUE, DIV, INK, INK_2, REF, RED, SURFACE, _footer, _save  # shared style

GROUP_LABEL = {"hike": "Hikes", "cut": "Cuts (scheduled)", "hold": "Holds",
               "moves_signed": "All moves,\nsigned (hike +, cut −)",
               "cut_incl_emergency": "Cuts incl. March 2020\nemergency cuts"}


def market_reaction_chart(conn: sqlite3.Connection) -> str:
    p = pd.read_sql_query("SELECT * FROM mart_event_path WHERE kind = 'index'", conn)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharey=True)
    for ax, g in zip(axes, ["hike", "cut", "hold"]):
        d = p[p["group"] == g].sort_values("day")
        mean, se = d["mean_car_from_start"] * 100, d["se"] * 100
        ax.axhline(0, color=REF, lw=1)
        ax.axvline(0, color=REF, lw=1, ls="--")
        ax.fill_between(d["day"], mean - 1.96 * se, mean + 1.96 * se, color=BLUE, alpha=0.15, lw=0)
        ax.plot(d["day"], mean, color=BLUE, lw=2, marker="o", ms=4)
        ax.set_title(f"{GROUP_LABEL[g]} ({int(d['n_events'].max())} decisions)", fontsize=11, loc="left")
        ax.set_xticks(range(-5, 6))
    axes[0].set_ylabel("Average cumulative abnormal return (%)")
    fig.supxlabel("Trading days from the decision (0 = announcement day)", fontsize=10.5,
                  color=INK_2, y=0.07)
    fig.suptitle("The FTSE 100 shows no consistent reaction to Bank Rate decisions",
                 fontsize=13, fontweight="bold", x=0.01, ha="left")
    _footer(fig, "Abnormal return = index return minus its average over trading days −250 to −11. "
                 "Cumulated from day −5. Shaded: 95% confidence interval. Source: Yahoo Finance, Bank of England.")
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    return _save(fig, "phase3_market_reaction.png")


def sector_volatility_chart(conn: sqlite3.Connection) -> str:
    v = pd.read_sql_query("SELECT * FROM mart_event_volatility", conn)
    v["label"] = v["series"].replace({config.INDEX_TICKER: "FTSE 100 index (market level)"})
    v = v.sort_values("variance_ratio")
    sig = v["q_fdr"] < config.FDR_LEVEL
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.barh(v["label"], v["variance_ratio"], color=np.where(sig, BLUE, "#c3c2b7"), height=0.65)
    ax.scatter(v["placebo_ratio_p95"], v["label"], marker="|", s=260, color=INK, zorder=3)
    ax.axvline(1, color=REF, lw=1, ls="--")
    for y, (val, q) in enumerate(zip(v["variance_ratio"], v["q_fdr"])):
        ax.text(val + 0.03, y, f"{val:.2f}×" + ("" if q < config.FDR_LEVEL else "  (not significant)"),
                va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, v["variance_ratio"].max() * 1.35)
    ax.set_xlabel("Size of abnormal moves on decision days relative to comparable days "
                  "(variance ratio; 1 = normal)")
    ax.grid(axis="y", visible=False)
    ax.set_title("On decision days, sectors move further from the market than usual;\n"
                 "the market as a whole does not", loc="left")
    _footer(fig, f"{int(v['n_events'].iloc[0])} scheduled decisions. Sectors: market-model abnormal "
                 "returns; index: return minus normal mean. Blue = significant after false-discovery "
                 "correction (q < 0.10).\nBlack tick = 95th percentile of placebo results. "
                 "Comparable days = Thursdays without a decision in the same "
                 "month and week of the month. Source: Yahoo Finance, Bank of England.")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return _save(fig, "phase3_sector_volatility.png")


def sector_direction_chart(conn: sqlite3.Connection) -> str:
    n_tests = int(pd.read_sql_query("SELECT COUNT(*) n FROM mart_event_results "
                                    "WHERE family = 'market_and_sector'", conn)["n"].iloc[0])
    r = pd.read_sql_query("SELECT * FROM mart_event_results WHERE kind = 'sector' AND window = 'm1_p1'", conn)
    groups =["hike", "cut", "hold", "moves_signed", "cut_incl_emergency"]
    r = r[r["group"].isin(groups) & (r["series"] != "All stocks (equal weight)")]
    mean = r.pivot(index="series", columns="group", values="mean")[groups] * 100
    p = r.pivot(index="series", columns="group", values="p_placebo")[groups]
    q = r.pivot(index="series", columns="group", values="q_fdr_placebo")[groups]
    mean = mean.sort_values("hike")

    fig, ax = plt.subplots(figsize=(11, 7.4))
    lim = np.nanmax(np.abs(mean.values))
    ax.imshow(mean.values, cmap=DIV, norm=TwoSlopeNorm(0, -lim, lim), aspect="auto")
    ax.set_xticks(range(len(groups)), [GROUP_LABEL[g] for g in groups])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(mean)), mean.index)
    ax.grid(False)
    ax.axvline(3.5, color=INK, lw=1.2)
    for i, s in enumerate(mean.index):
        for j, g in enumerate(groups):
            v = mean.at[s, g]
            mark = "**" if q.at[s, g] < config.FDR_LEVEL else ("*" if p.at[s, g] < 0.05 else "")
            ax.text(j, i, f"{v:+.2f}%{mark}", ha="center", va="center", fontsize=9.5,
                    color="white" if abs(v) > lim * 0.75 else INK)
    ax.set_title("Sector returns relative to the market around decisions (days −1 to +1):\n"
                 "small, and mostly within what chance produces", loc="left", pad=44)
    _footer(fig, f"Average market-model abnormal return. * placebo p < 0.05 (could be chance among {n_tests} tests); "
                 "** still significant after false-discovery correction.\nThe right-hand column includes the "
                 "March 2020 emergency cuts, which coincided with the Covid crash. Source: Yahoo Finance, "
                 "Bank of England.")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return _save(fig, "phase3_sector_direction.png")


def placebo_chart(conn: sqlite3.Connection) -> str:
    ex = pd.read_sql_query("SELECT * FROM mart_event_placebo_examples", conn)
    titles = {
        (config.INDEX_TICKER, "hike"): "FTSE 100, hike days (day 0)",
        ("Real Estate", "hike"): "Real Estate vs market,\nhikes (days −1 to +1)",
        ("Utilities", "cut_incl_emergency"): "Utilities vs market, cuts incl.\nMarch 2020 (days −1 to +1)",
    }
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    for ax, ((series, g), title) in zip(axes, titles.items()):
        d = ex[(ex["series"] == series) & (ex["group"] == g)]
        actual, pv = d["actual_mean"].iloc[0] * 100, d["p_placebo"].iloc[0]
        ax.hist(d["placebo_mean"] * 100, bins=50, color="#86b6ef", edgecolor=SURFACE, lw=0.5)
        ax.axvline(actual, color=RED, lw=2.2)
        centre = float(np.median(d["placebo_mean"] * 100))
        ax.axvline(centre, color=INK_2, lw=1, ls=":")
        right = actual < centre  # put the label on the side away from the red line
        ax.text(0.98 if right else 0.02, 0.97,
                f"Real decisions: {actual:+.2f}%\nPlacebo centre: {centre:+.2f}%\np = {pv:.3f}",
                transform=ax.transAxes, color=INK, fontsize=9, va="top", ha="right" if right else "left",
                bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.9, "pad": 2})
        ax.set_title(title, fontsize=10.5, loc="left")
        ax.set_xlabel("Average abnormal return (%)")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Number of placebo samples")
    fig.suptitle("Placebo test: real decision days compared with 2,000 sets of comparable non-decision days",
                 fontsize=13, fontweight="bold", x=0.01, ha="left")
    _footer(fig, "Blue: results on placebo days (Thursdays with no decision, same month and week of the month). "
                 "Red: the real decisions. Dotted: centre of the placebo results.\n"
                 "p = how unusual the real result is within the placebo distribution (two-sided).")
    fig.tight_layout(rect=(0, 0.08, 1, 0.93))
    return _save(fig, "phase3_placebo.png")


def make_all(conn: sqlite3.Connection) -> list[str]:
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return [market_reaction_chart(conn), sector_volatility_chart(conn),
            sector_direction_chart(conn), placebo_chart(conn)]
