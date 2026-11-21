"""FTSE 100 Risk & Rates Lab: interactive results.

Reads the small summary tables in app/data/, which the daily GitHub Actions
job rebuilds from the full pipeline (python run_pipeline.py). Every number on
the page is calculated from those tables, so the text stays correct after
each refresh.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"
REPO = "https://github.com/CodeColonizer/ftse100-risk-rates-lab"

BLUE, RED, GREY, INK2 = "#2a78d6", "#e34948", "#8a8984", "#52514e"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
INDEX_NAME = "FTSE 100 index (price only)"
EW_NAME = "All stocks (equal weight)"
EXTRA_SECTORS = {"All stocks (equal weight)", "Financials excl. investment trusts",
                 "FTSE 100 index (price)"}
GROUP_LABELS = {"hike": "Hikes", "cut": "Cuts (scheduled)", "hold": "Holds",
                "moves_signed": "All moves, signed (hike +, cut −)",
                "cut_incl_emergency": "Cuts incl. March 2020 emergency cuts",
                "all_scheduled": "All scheduled decisions"}
WINDOW_LABELS = {"day0": "Announcement day (day 0)", "m1_p1": "Days −1 to +1",
                 "d0_p5": "Days 0 to +5"}

st.set_page_config(page_title="FTSE 100 Risk & Rates Lab", page_icon="📉", layout="wide")


# ----------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def load() -> dict:
    if not (DATA / "meta.json").exists():
        return {}
    d = {p.stem: pd.read_csv(p) for p in DATA.glob("*.csv")}
    d["meta"] = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    for name in ["sector_growth", "rolling_corr"]:
        d[name]["date"] = pd.to_datetime(d[name]["date"])
    d["boe_decisions"]["decision_date"] = pd.to_datetime(d["boe_decisions"]["decision_date"])
    return d


D = load()
if not D:
    st.error("No app data found. Run `python run_pipeline.py` to build `app/data/`.")
    st.stop()
META = D["meta"]

try:  # follow the viewer's light or dark theme for chart text
    DARK = st.context.theme.type == "dark"
except Exception:
    DARK = False
TEXT = "#f0efec" if DARK else "#0b0b0b"
Y_LABELS = alt.Axis(labelLimit=240)


def pct(x: float, digits: int = 1, sign: bool = False) -> str:
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def chart(c: alt.Chart) -> None:
    st.altair_chart(c, width="stretch")


def core_sectors(df: pd.DataFrame, col: str = "sector") -> pd.DataFrame:
    return df[~df[col].isin(EXTRA_SECTORS)]


sector_risk = D["sector_risk"]
sectors = core_sectors(sector_risk)
index_row = sector_risk[sector_risk["sector"] == "FTSE 100 index (price)"].iloc[0]

# ----------------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------------

st.title("FTSE 100 Risk & Rates Lab")
st.markdown(
    "**How risky are UK large-cap stocks and sectors, which sectors actually diversify a "
    "portfolio, and how do stocks react to Bank of England interest rate decisions?**")
st.caption(
    f"Data from January 2010 to {pd.Timestamp(META['data_through']):%d %B %Y}, refreshed every "
    f"weekday (last build {META['built_at_utc']} UTC). Covers today's {META['n_stocks']} FTSE 100 "
    "members. Figures describe the past; nothing here is a forecast or investment advice. "
    f"[Code and full write-up on GitHub]({REPO}).")

tabs = st.tabs(["Overview", "Sector risk", "Diversification", "Stress periods",
                "Bank Rate decisions", "Data & method"])

# ----------------------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------------------

with tabs[0]:
    q = META["quality"]
    last = META["last_decision"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bank Rate", f"{META['bank_rate_now_pct']:.2f}%",
              f"{last['decision']} on {pd.Timestamp(last['date']):%d %b %Y}", delta_color="off")
    c2.metric("Data through", f"{pd.Timestamp(META['data_through']):%d %b %Y}")
    c3.metric("Rate decisions studied", f"{META['n_decisions_analysed']}",
              f"of {META['n_decisions_total']} since 2010", delta_color="off")
    c4.metric("Data quality checks passed", f"{q['passed'] + q['for_review']} of {q['checks']}",
              f"{q['failed']} failed · {q['for_review']} with items to review", delta_color="off")

    by_vol = sectors.sort_values("ann_volatility")
    diversifiers = sectors.sort_values("beta").head(3)
    stress = D["stress_periods"]
    corr_full = stress.query("kind == 'summary' and period == 'full_period'")["value"].iloc[0]
    corr_covid = stress.query("kind == 'summary' and period == 'covid_crash'")["value"].iloc[0]
    hikes = stress.query("kind == 'sector' and period == 'hikes_2022' and name != @EW_NAME")
    best, worst = hikes.loc[hikes["window_return"].idxmax()], hikes.loc[hikes["window_return"].idxmin()]
    vol = D["event_volatility"]
    vol_sec = core_sectors(vol[vol["kind"] == "sector"], "series")
    n_vol_sig = int((vol_sec["q_fdr"] < META["fdr_level"]).sum())
    idx_vol = vol[vol["kind"] == "index"].iloc[0]
    ev = D["event_results"]
    n_dir_sig = int((ev["q_fdr_placebo"] < META["fdr_level"]).sum())

    st.subheader("Key findings")
    st.markdown(f"""
- **Riskiest and steadiest sectors.** {by_vol.iloc[-1]['sector']} and {by_vol.iloc[-2]['sector']}
  swing most ({pct(by_vol.iloc[-1]['ann_volatility'], 0)} and {pct(by_vol.iloc[-2]['ann_volatility'], 0)}
  annualised volatility); {by_vol.iloc[0]['sector']} least ({pct(by_vol.iloc[0]['ann_volatility'], 0)}).
- **Best diversifiers.** {', '.join(diversifiers['sector'])} move least with the market
  (beta {diversifiers['beta'].min():.2f}–{diversifiers['beta'].max():.2f}).
- **Diversification fails in a crash.** The average correlation between sectors rose from
  {corr_full:.2f} to {corr_covid:.2f} in the Covid crash.
- **Rising rates split the market.** In 2022 {best['name']} returned {pct(best['window_return'], 0, True)}
  while {worst['name']} returned {pct(worst['window_return'], 0, True)}.
- **Bank Rate decisions move sectors, not the market.** On decision days, {n_vol_sig} of
  {len(vol_sec)} sectors move further from the market than on comparable days; the FTSE 100 itself
  {"does" if idx_vol['q_fdr'] < META['fdr_level'] else "does not"} move more than usual.
- **Hike, cut or hold does not predict the direction.** {n_dir_sig} of {len(ev)} market and sector
  tests remain significant after correcting for multiple testing.
""")

    g = D["sector_growth"]
    g = g[g["series"].isin([EW_NAME, INDEX_NAME])]
    st.markdown("**Growth of £100 since January 2010** (equal-weighted stocks include dividends; "
                "the FTSE 100 price index does not)")
    chart(alt.Chart(g).mark_line(strokeWidth=2).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("growth_of_100:Q", title="Value of £100", scale=alt.Scale(type="log")),
        color=alt.Color("series:N", title=None, scale=alt.Scale(
            domain=[EW_NAME, INDEX_NAME], range=[BLUE, GREY]), legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("date:T", title="Week ending"),
                 alt.Tooltip("growth_of_100:Q", title="Value of £100", format=",.0f")],
    ).properties(height=320))
    st.caption("Log scale. Today's members only (survivorship bias), so past growth is overstated "
               "compared with holding the index as it was at the time.")

# ----------------------------------------------------------------------------------
# Sector risk
# ----------------------------------------------------------------------------------

METRICS = {
    "Annualised volatility": ("ann_volatility", True, "How much returns swing in a typical year"),
    "Worst fall (max drawdown)": ("max_drawdown", True, "Largest drop from a peak to a later low"),
    "Beta to the FTSE 100": ("beta", False, "Moves per 1% move in the index"),
    "Sharpe ratio": ("sharpe", False, "Return above Bank Rate per unit of volatility"),
    "Annual return": ("ann_return", True, "Compound growth rate, dividends included"),
}

with tabs[1]:
    left, right = st.columns([1, 1])
    with left:
        label = st.selectbox("Measure", list(METRICS), key="risk_metric")
        col, is_pct, help_text = METRICS[label]
        st.caption(help_text)
        data = sector_risk[sector_risk["sector"].isin(set(sectors["sector"]) | {"FTSE 100 index (price)"})].copy()
        data["value"] = data[col] * (100 if is_pct else 1)
        data["type"] = data["sector"].map(lambda s: "Index" if s.startswith("FTSE") else "Sector")
        chart(alt.Chart(data).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("value:Q", title=label + (" (%)" if is_pct else "")),
            y=alt.Y("sector:N", sort="-x" if col != "max_drawdown" else "x", title=None, axis=Y_LABELS),
            color=alt.Color("type:N", scale=alt.Scale(domain=["Sector", "Index"], range=[BLUE, GREY]),
                            legend=None),
            tooltip=[alt.Tooltip("sector:N", title="Sector"),
                     alt.Tooltip("value:Q", title=label, format=".2f")],
        ).properties(height=380))
    with right:
        options = sorted(sectors["sector"]) + [EW_NAME]
        chosen = st.multiselect("Compare growth of £100 (up to 5)", options,
                                default=["Energy", "Real Estate", "Health Care"], max_selections=5)
        log = st.toggle("Log scale", value=True)
        g = D["sector_growth"]
        g = g[g["series"].isin(chosen + [INDEX_NAME])]
        domain = chosen + [INDEX_NAME]
        chart(alt.Chart(g).mark_line(strokeWidth=2).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("growth_of_100:Q", title="Value of £100",
                    scale=alt.Scale(type="log" if log else "linear")),
            color=alt.Color("series:N", title=None, sort=domain, scale=alt.Scale(
                domain=domain, range=CATEGORICAL[:len(chosen)] + [GREY]),
                legend=alt.Legend(orient="top", columns=3)),
            tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("date:T", title="Week ending"),
                     alt.Tooltip("growth_of_100:Q", title="Value of £100", format=",.0f")],
        ).properties(height=380))

    st.markdown("**All sectors**")
    t = sector_risk[["sector", "n_stocks_today", "ann_volatility", "max_drawdown", "beta",
                     "corr_with_index", "sharpe", "ann_return", "trough_date", "recovery_date"]].copy()
    for c in ["ann_volatility", "max_drawdown", "ann_return"]:
        t[c] = t[c] * 100
    st.dataframe(t.sort_values("ann_volatility"), hide_index=True, width="stretch", column_config={
        "sector": "Sector", "n_stocks_today": st.column_config.NumberColumn("Stocks", format="%d"),
        "ann_volatility": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
        "max_drawdown": st.column_config.NumberColumn("Worst fall", format="%.0f%%"),
        "beta": st.column_config.NumberColumn("Beta", format="%.2f"),
        "corr_with_index": st.column_config.NumberColumn("Corr. with index", format="%.2f"),
        "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
        "ann_return": st.column_config.NumberColumn("Annual return", format="%.1f%%"),
        "trough_date": "Worst fall: low", "recovery_date": "Recovered"})

    st.markdown("**Individual stocks**")
    sec_filter = st.selectbox("Sector", ["All sectors"] + sorted(sectors["sector"]), key="stock_sector")
    s = D["stock_risk"][D["stock_risk"]["ticker"] != "^FTSE"].copy()
    if sec_filter != "All sectors":
        s = s[s["icb_industry"] == sec_filter]
    for c in ["ann_volatility", "max_drawdown", "ann_return", "worst_day_return"]:
        s[c] = s[c] * 100
    s["history"] = s["short_history"].map({1: "under 3 years", 0: ""})
    st.dataframe(
        s[["company", "ticker", "icb_industry", "years", "ann_volatility", "max_drawdown", "beta",
           "sharpe", "ann_return", "worst_day_return", "worst_day_date", "history"]]
        .sort_values("ann_volatility", ascending=False),
        hide_index=True, width="stretch", column_config={
            "company": "Company", "ticker": "Ticker", "icb_industry": "Sector",
            "years": st.column_config.NumberColumn("Years of data", format="%.1f"),
            "ann_volatility": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
            "max_drawdown": st.column_config.NumberColumn("Worst fall", format="%.0f%%"),
            "beta": st.column_config.NumberColumn("Beta", format="%.2f"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "ann_return": st.column_config.NumberColumn("Annual return", format="%.1f%%"),
            "worst_day_return": st.column_config.NumberColumn("Worst day", format="%.1f%%"),
            "worst_day_date": "Worst day date", "history": "Note"})
    st.caption("Sectors are equal-weighted portfolios of today's members, rebalanced daily. "
               "Returns include dividends; the FTSE 100 index does not.")

# ----------------------------------------------------------------------------------
# Diversification
# ----------------------------------------------------------------------------------

with tabs[2]:
    st.markdown("A sector diversifies a FTSE 100 portfolio if it moves **less** than the market "
                "(low beta) and **differently** from it (low correlation): bottom-left is best.")
    pts = sectors[["sector", "beta", "corr_with_index", "ann_volatility"]]
    base = alt.Chart(pts).encode(
        x=alt.X("beta:Q", title="Beta to the FTSE 100", scale=alt.Scale(zero=False, padding=30)),
        y=alt.Y("corr_with_index:Q", title="Correlation with the FTSE 100",
                scale=alt.Scale(zero=False, padding=20)),
        tooltip=[alt.Tooltip("sector:N", title="Sector"), alt.Tooltip("beta:Q", title="Beta", format=".2f"),
                 alt.Tooltip("corr_with_index:Q", title="Correlation", format=".2f"),
                 alt.Tooltip("ann_volatility:Q", title="Volatility", format=".1%")])
    one = alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(strokeDash=[4, 4], color=GREY).encode(x="x:Q")
    chart((one + base.mark_circle(size=140, color=BLUE, opacity=1)
           + base.mark_text(align="left", dx=10, fontSize=12, color=TEXT).encode(text="sector:N")).properties(height=420))

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Correlation between sectors** (daily returns, whole period)")
        corr = D["sector_correlation"]
        order = corr.groupby("sector_a")["correlation"].mean().sort_values().index.tolist()
        off = corr[corr["sector_a"] != corr["sector_b"]]
        heat = alt.Chart(off).encode(
            x=alt.X("sector_b:N", sort=order, title=None,
                    axis=alt.Axis(labelAngle=-45, labelOverlap=False, labelLimit=240)),
            y=alt.Y("sector_a:N", sort=order, title=None, axis=Y_LABELS))
        chart((heat.mark_rect().encode(
            color=alt.Color("correlation:Q", title="Correlation",
                            scale=alt.Scale(scheme="blues", domain=[0.2, 0.9])),
            tooltip=[alt.Tooltip("sector_a:N", title="Sector"), alt.Tooltip("sector_b:N", title="With"),
                     alt.Tooltip("correlation:Q", title="Correlation", format=".2f")])
               + heat.mark_text(fontSize=10).encode(
                   text=alt.Text("correlation:Q", format=".2f"),
                   color=alt.condition("datum.correlation > 0.62", alt.value("white"), alt.value("black"))))
              .properties(height=440))
    with c2:
        st.markdown("**One-year rolling correlation with the FTSE 100**")
        rc = D["rolling_corr"]
        pick = st.selectbox("Sector", sorted(rc["sector"].unique()), key="roll_sector",
                            index=sorted(rc["sector"].unique()).index("Energy"))
        med = rc.groupby("date", as_index=False)["corr_with_index"].median().assign(series="Median of all sectors")
        one_s = rc[rc["sector"] == pick].assign(series=pick)
        both = pd.concat([one_s[["date", "corr_with_index", "series"]], med])
        bands = D["stress_definitions"].assign(base_date=lambda d: pd.to_datetime(d["base_date"]),
                                               end_date=lambda d: pd.to_datetime(d["end_date"]))
        shade = alt.Chart(bands).mark_rect(color=RED, opacity=0.12).encode(
            x="base_date:T", x2="end_date:T", tooltip=[alt.Tooltip("label:N", title="Stress period")])
        lines = alt.Chart(both).mark_line(strokeWidth=2).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("corr_with_index:Q", title="Correlation", scale=alt.Scale(domain=[-0.3, 1])),
            color=alt.Color("series:N", title=None, scale=alt.Scale(
                domain=[pick, "Median of all sectors"], range=[BLUE, GREY]), legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("date:T", title="Week ending"),
                     alt.Tooltip("corr_with_index:Q", title="Correlation", format=".2f")])
        chart((shade + lines).properties(height=400))
        st.caption("Shaded: the three stress periods. Correlation over the previous 252 trading days.")

# ----------------------------------------------------------------------------------
# Stress periods
# ----------------------------------------------------------------------------------

with tabs[3]:
    defs = D["stress_definitions"]
    label_to_period = dict(zip(defs["label"], defs["period"]))
    choice = st.radio("Period", list(label_to_period), horizontal=True)
    p = label_to_period[choice]
    row = defs[defs["period"] == p].iloc[0]
    st.caption(f"{pd.Timestamp(row['base_date']):%d %b %Y} to {pd.Timestamp(row['end_date']):%d %b %Y}. "
               f"{row['why']}")
    st_ = D["stress_periods"]
    sec = st_[(st_["period"] == p) & (st_["kind"].isin(["sector", "index"]))].copy()
    sec["name"] = sec["name"].replace({"^FTSE": "FTSE 100 index"})
    sec["pct"] = sec["window_return"] * 100
    sec["sign"] = sec["pct"].map(lambda v: "Gain" if v >= 0 else "Loss")
    idx_val = sec.loc[sec["name"] == "FTSE 100 index", "pct"].iloc[0]
    corr_val = st_.query("kind == 'summary' and period == @p")["value"].iloc[0]
    c1, c2 = st.columns([3, 2])
    with c1:
        bars = alt.Chart(sec[sec["name"] != "FTSE 100 index"]).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("pct:Q", title="Return over the period (%)"),
            y=alt.Y("name:N", sort="-x", title=None, axis=Y_LABELS),
            color=alt.Color("sign:N", scale=alt.Scale(domain=["Gain", "Loss"], range=[BLUE, RED]), legend=None),
            tooltip=[alt.Tooltip("name:N", title="Sector"), alt.Tooltip("pct:Q", title="Return (%)", format="+.1f")])
        rule = alt.Chart(pd.DataFrame({"x": [idx_val]})).mark_rule(color=GREY, strokeDash=[4, 4], size=2).encode(
            x="x:Q")
        chart((bars + rule).properties(height=420))
        st.caption(f"Dashed line: FTSE 100 index ({idx_val:+.1f}%, price only). Sectors include dividends. "
                   f"Average correlation between sectors in this period: {corr_val:.2f}.")
    with c2:
        stocks = st_[(st_["period"] == p) & (st_["kind"] == "stock")].merge(
            D["stock_risk"][["ticker", "company"]], left_on="name", right_on="ticker", how="left")
        stocks["Return"] = stocks["window_return"] * 100
        cfg = {"company": "Company", "Return": st.column_config.NumberColumn("Return", format="%+.1f%%")}
        st.markdown("**Best five stocks**")
        st.dataframe(stocks.nlargest(5, "Return")[["company", "Return"]], hide_index=True,
                     width="stretch", column_config=cfg)
        st.markdown("**Worst five stocks**")
        st.dataframe(stocks.nsmallest(5, "Return")[["company", "Return"]], hide_index=True,
                     width="stretch", column_config=cfg)

# ----------------------------------------------------------------------------------
# Bank Rate decisions
# ----------------------------------------------------------------------------------

with tabs[4]:
    dec = D["boe_decisions"]
    st.markdown(
        f"**{META['n_decisions_analysed']} Monetary Policy Committee decisions** analysed with an event "
        "study. For each decision, a stock's or sector's *abnormal return* is its actual return minus "
        "what was normal for it: for sectors, what the FTSE 100's move that day would predict. Results "
        f"are compared with {META['placebo_draws']:,} sets of comparable days without a decision "
        "(Thursdays in the same month and week of the month).")

    steps = alt.Chart(dec).mark_line(interpolate="step-after", color=BLUE, strokeWidth=2).encode(
        x=alt.X("decision_date:T", title=None), y=alt.Y("new_rate_pct:Q", title="Bank Rate (%)"))
    marks = alt.Chart(dec[dec["decision"] != "hold"]).mark_point(filled=True, size=70).encode(
        x="decision_date:T", y="new_rate_pct:Q",
        shape=alt.Shape("decision:N", scale=alt.Scale(domain=["hike", "cut"], range=["triangle-up", "triangle-down"]),
                        title=None, legend=alt.Legend(orient="top")),
        color=alt.Color("decision:N", scale=alt.Scale(domain=["hike", "cut"], range=[RED, "#1baf7a"]), title=None),
        tooltip=[alt.Tooltip("decision_date:T", title="Date"), alt.Tooltip("decision:N", title="Decision"),
                 alt.Tooltip("old_rate_pct:Q", title="From (%)"), alt.Tooltip("new_rate_pct:Q", title="To (%)")])
    chart((steps + marks).properties(height=240))

    st.subheader("1. Does the market move more than usual on decision days?")
    vol = D["event_volatility"].copy()
    vol["label"] = vol["series"].replace({"^FTSE": "FTSE 100 index (market level)"})
    vol["result"] = vol["q_fdr"].map(lambda q: "Significant" if q < META["fdr_level"] else "Not significant")
    chart(alt.Chart(vol).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("variance_ratio:Q", title="Size of moves on decision days vs comparable days (1 = normal)"),
        y=alt.Y("label:N", sort="-x", title=None, axis=Y_LABELS),
        color=alt.Color("result:N", scale=alt.Scale(domain=["Significant", "Not significant"],
                                                    range=[BLUE, "#c3c2b7"]), title=None,
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("label:N", title="Series"),
                 alt.Tooltip("variance_ratio:Q", title="Variance ratio", format=".2f"),
                 alt.Tooltip("p_placebo_one_sided:Q", title="Placebo p", format=".3f"),
                 alt.Tooltip("q_fdr:Q", title="q (corrected)", format=".3f")],
    ) + alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(strokeDash=[4, 4], color=GREY).encode(x="x:Q"))
    st.caption("Sectors: moves relative to the market. Index: moves relative to its normal average. "
               f"Significant = false-discovery-adjusted q < {META['fdr_level']:.2f}.")

    st.subheader("2. Which way do sectors move, by type of decision?")
    c1, c2 = st.columns(2)
    group = c1.selectbox("Decisions", ["hike", "cut", "hold", "moves_signed", "cut_incl_emergency"],
                         format_func=GROUP_LABELS.get)
    window = c2.selectbox("Window", list(WINDOW_LABELS), index=1, format_func=WINDOW_LABELS.get)
    ev = D["event_results"]
    sel = ev[(ev["group"] == group) & (ev["window"] == window)].copy()
    sel["label"] = sel["series"].replace({"^FTSE": "FTSE 100 (vs its normal average)"})
    for c in ["mean", "ci95_low", "ci95_high", "placebo_centre"]:
        sel[c] = sel[c] * 100
    sel["significance"] = sel.apply(
        lambda r: "Significant after correction" if r["q_fdr_placebo"] < META["fdr_level"]
        else ("p < 0.05, could be chance" if r["p_placebo"] < 0.05 else "Within chance"), axis=1)
    n_ev = int(sel["n_events"].max())
    base = alt.Chart(sel).encode(y=alt.Y("label:N", sort="-x", title=None, axis=Y_LABELS))
    chart((base.mark_rule(color=GREY).encode(x=alt.X("ci95_low:Q", title="Average abnormal return (%)"),
                                            x2="ci95_high:Q")
           + base.mark_point(filled=True, size=110).encode(
               x="mean:Q",
               color=alt.Color("significance:N", title=None, legend=alt.Legend(orient="top"),
                               scale=alt.Scale(domain=["Significant after correction",
                                                       "p < 0.05, could be chance", "Within chance"],
                                               range=[RED, "#eda100", BLUE])),
               tooltip=[alt.Tooltip("label:N", title="Series"),
                        alt.Tooltip("n_events:Q", title="Decisions"),
                        alt.Tooltip("mean:Q", title="Average (%)", format="+.2f"),
                        alt.Tooltip("placebo_centre:Q", title="Comparable days (%)", format="+.2f"),
                        alt.Tooltip("p_placebo:Q", title="Placebo p", format=".3f"),
                        alt.Tooltip("q_fdr_placebo:Q", title="q (corrected)", format=".3f")])
           + alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=GREY).encode(x="x:Q"))
          .properties(height=440))
    st.caption(f"{GROUP_LABELS[group]}: {n_ev} decisions. Grey bars: 95% confidence interval. "
               "The 2020 emergency cuts coincided with the Covid crash, so their results cannot be "
               "attributed to the rate cut.")

    st.subheader("3. The FTSE 100 around decisions")
    pg = st.radio("Decisions", ["hike", "cut", "hold"], format_func=GROUP_LABELS.get, horizontal=True,
                  key="path_group")
    path = D["event_path"]
    path = path[(path["kind"] == "index") & (path["group"] == pg)].copy()
    path["mean"] = path["mean_car_from_start"] * 100
    path["lo"] = path["mean"] - 196 * path["se"]
    path["hi"] = path["mean"] + 196 * path["se"]
    pb = alt.Chart(path).encode(x=alt.X("day:Q", title="Trading days from the decision (0 = announcement)",
                                        scale=alt.Scale(domain=[-5, 5])))
    chart((pb.mark_area(color=BLUE, opacity=0.15).encode(y=alt.Y("lo:Q", title="Average cumulative abnormal return (%)"),
                                                         y2="hi:Q")
           + pb.mark_line(color=BLUE, point=True).encode(
               y="mean:Q", tooltip=[alt.Tooltip("day:Q", title="Day"),
                                    alt.Tooltip("mean:Q", title="Average (%)", format="+.2f")])
           + alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=GREY).encode(y="y:Q"))
          .properties(height=280))

    stock_res = D["event_stock_results"]
    n_stock_sig = int((stock_res["q_fdr_placebo"] < META["fdr_level"]).sum())
    st.info(
        "**Reading these results.** Markets largely anticipate Bank Rate decisions, so what moves "
        "prices is the surprise and the Bank's guidance, which this study cannot measure with free "
        "data. Decision days bring above-normal *sector rotation*, but knowing whether the Bank "
        "hiked, cut or held does not reliably predict which way a sector goes. At stock level, "
        f"{n_stock_sig} of {len(stock_res)} tests over days −1 to +1 survive the correction.")

# ----------------------------------------------------------------------------------
# Data & method
# ----------------------------------------------------------------------------------

with tabs[5]:
    qr = D["quality_report"]
    q = META["quality"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Checks passed", q["passed"])
    c2.metric("Passed, items listed for review", q["for_review"])
    c3.metric("Failed", q["failed"])
    st.markdown("**Checks with items to review** (kept in the data, listed for transparency)")
    st.dataframe(qr[qr["status"] != "pass"][["check", "description", "rows_flagged", "examples"]],
                 hide_index=True, width="stretch",
                 column_config={"check": "Check", "description": "What it checks",
                                "rows_flagged": st.column_config.NumberColumn("Items", format="%d"),
                                "examples": "Examples"})
    with st.expander("All data quality checks"):
        st.dataframe(qr[["check", "severity", "status", "rows_flagged", "description"]],
                     hide_index=True, width="stretch")

    st.markdown(f"""
**Data.** Daily prices and dividends from Yahoo Finance for today's FTSE 100 members and the
FTSE 100 index since January 2010; Bank Rate and every MPC decision from the Bank of England.
Raw prices are not stored in this app or the repository; the app reads summary tables rebuilt each
weekday by an automated job that only publishes if every required data quality check and test passes.

**Method.** Total returns (price plus dividends) on London trading days, with documented corrections
for data errors. Sectors are equal-weighted portfolios of ICB industries. The event study uses
market-model abnormal returns, a calendar-matched placebo test and a false-discovery-rate correction.

**Limitations.**
- *Survivorship bias:* only today's members are included, so history looks better than it was.
- *Look-ahead bias:* today's sector labels are applied to the whole period.
- *Benchmark:* the FTSE 100 index is a price index without dividends.
- *Free data:* Yahoo Finance is not audited; its dividend-adjusted prices for London stocks were
  found to be wrong and are rebuilt from dividend records.
- *No rate-surprise measure:* decisions are grouped by type, not by how unexpected they were.
- *Not advice:* this describes the past and makes no predictions.

Full findings, decision log and code: [GitHub repository]({REPO}) ·
[Phase 2 findings]({REPO}/blob/main/docs/phase2_findings.md) ·
[Phase 3 findings]({REPO}/blob/main/docs/phase3_findings.md) ·
[Decision log]({REPO}/blob/main/docs/decisions.md)
""")
