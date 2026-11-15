"""Run the full FTSE 100 Risk & Rates Lab pipeline: data, quality checks, risk
analytics and the Bank Rate event study.

    python run_pipeline.py                         download everything, rebuild, check
    python run_pipeline.py --offline               rebuild from cached downloads
    python run_pipeline.py --refresh-constituents  take a new dated constituents snapshot first

Exits with code 1 if any 'error' data quality check fails.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from ftselab import (  # noqa: E402
    app_data, boe, charts, config, constituents, db, event_charts, events, prices, quality, risk,
    risk_charts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="use cached downloads in data/raw/")
    parser.add_argument("--refresh-constituents", action="store_true",
                        help="take a new constituents snapshot from Wikipedia before running")
    args = parser.parse_args(argv)
    t0 = time.time()

    print("1/11 Constituents")
    if args.refresh_constituents:
        print(f"  new snapshot: {constituents.refresh_snapshot()}")
    snap_path = constituents.latest_snapshot_path()
    cons = constituents.load_snapshot(snap_path)
    print(f"  using {snap_path.name}: {len(cons)} companies")

    print("2/11 Bank of England data")
    decisions, bank_rate = boe.refresh(offline=args.offline)
    print(f"  {len(decisions)} MPC decisions since {config.START_DATE}; "
          f"{len(bank_rate)} daily Bank Rate observations")

    print("3/11 Prices (Yahoo Finance)")
    tickers = [config.INDEX_TICKER] + cons["yahoo_ticker"].tolist()
    raw_prices, info, fx, dividends = prices.refresh(tickers, offline=args.offline)
    print(f"  {len(raw_prices):,} raw price rows for {raw_prices['ticker'].nunique()} tickers; "
          f"{len(dividends):,} dividends; {len(fx):,} FX rows")
    corrections = pd.read_csv(config.PRICE_CORRECTIONS_FILE)
    print(f"  {len(corrections)} documented price corrections")

    print("4/11 Loading raw layer and building clean layer")
    conn = db.connect()
    try:
        db.load_raw(conn, {
            "prices": raw_prices, "ticker_info": info, "fx": fx, "dividends": dividends,
            "price_corrections": corrections, "constituents": cons,
            "boe_decisions": decisions, "bank_rate_daily": bank_rate,
        })
        ran = db.build_clean(conn)
        print(f"  ran {', '.join(ran)}")

        print("5/11 Data quality checks")
        report = quality.run_checks(conn)
        quality.write_report(report)
        for r in report.itertuples():
            mark = {"pass": "ok  ", "review": "note", "fail": "FAIL"}[r.status]
            print(f"  [{mark}] {r.check}: {r.rows_flagged} flagged")

        print("6/11 Data charts")
        for path in charts.make_all(conn):
            print(f"  {path}")

        failed = report[report["status"] == "fail"]
        if failed.empty:
            print("7/11 Risk analytics")
            tables = risk.build(conn)
            print(f"  wrote {len(tables)} mart_ tables and outputs/tables/*.csv")
            print("8/11 Risk charts")
            for path in risk_charts.make_all(conn):
                print(f"  {path}")
            print("9/11 Event study of Bank Rate decisions")
            ev = events.build(conn)
            n_ev = int(ev["mart_event_list"]["included"].sum())
            print(f"  {n_ev} decisions analysed; {len(ev['mart_event_results']):,} tests with placebo p-values")
            print("10/11 Event study charts")
            for path in event_charts.make_all(conn):
                print(f"  {path}")
            print("11/11 Data for the Streamlit app")
            files = app_data.export(conn)
            print(f"  {len(files)} files, {app_data.total_size_kb():.0f} KB in app/data/")
        else:
            print("Steps 7 to 11 skipped: fix the failed data quality checks first")
    finally:
        conn.close()

    print(f"Done in {time.time() - t0:.0f}s. Database: {config.DB_PATH}")
    if not failed.empty:
        print(f"{len(failed)} data quality check(s) FAILED - see outputs/data_quality_report.csv")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
