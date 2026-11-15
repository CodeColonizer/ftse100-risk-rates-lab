"""Run the full FTSE 100 Risk & Rates Lab pipeline: data, quality checks, risk analytics.

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
    boe, charts, config, constituents, db, prices, quality, risk, risk_charts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="use cached downloads in data/raw/")
    parser.add_argument("--refresh-constituents", action="store_true",
                        help="take a new constituents snapshot from Wikipedia before running")
    args = parser.parse_args(argv)
    t0 = time.time()

    print("1/8 Constituents")
    if args.refresh_constituents:
        print(f"  new snapshot: {constituents.refresh_snapshot()}")
    snap_path = constituents.latest_snapshot_path()
    cons = constituents.load_snapshot(snap_path)
    print(f"  using {snap_path.name}: {len(cons)} companies")

    print("2/8 Bank of England data")
    decisions, bank_rate = boe.refresh(offline=args.offline)
    print(f"  {len(decisions)} MPC decisions since {config.START_DATE}; "
          f"{len(bank_rate)} daily Bank Rate observations")

    print("3/8 Prices (Yahoo Finance)")
    tickers = [config.INDEX_TICKER] + cons["yahoo_ticker"].tolist()
    raw_prices, info, fx = prices.refresh(tickers, offline=args.offline)
    print(f"  {len(raw_prices):,} raw price rows for {raw_prices['ticker'].nunique()} tickers; "
          f"{len(fx):,} FX rows")
    corrections = pd.read_csv(config.PRICE_CORRECTIONS_FILE)
    print(f"  {len(corrections)} documented price corrections")

    print("4/8 Loading raw layer and building clean layer")
    conn = db.connect()
    try:
        db.load_raw(conn, {
            "prices": raw_prices, "ticker_info": info, "fx": fx,
            "price_corrections": corrections, "constituents": cons,
            "boe_decisions": decisions, "bank_rate_daily": bank_rate,
        })
        ran = db.build_clean(conn)
        print(f"  ran {', '.join(ran)}")

        print("5/8 Data quality checks")
        report = quality.run_checks(conn)
        quality.write_report(report)
        for r in report.itertuples():
            mark = {"pass": "ok  ", "review": "note", "fail": "FAIL"}[r.status]
            print(f"  [{mark}] {r.check}: {r.rows_flagged} flagged")

        print("6/8 Data charts")
        for path in charts.make_all(conn):
            print(f"  {path}")

        failed = report[report["status"] == "fail"]
        if failed.empty:
            print("7/8 Risk analytics")
            tables = risk.build(conn)
            print(f"  wrote {len(tables)} mart_ tables and outputs/tables/*.csv")
            print("8/8 Risk charts")
            for path in risk_charts.make_all(conn):
                print(f"  {path}")
        else:
            print("7/8 and 8/8 skipped: fix the failed data quality checks first")
    finally:
        conn.close()

    print(f"Done in {time.time() - t0:.0f}s. Database: {config.DB_PATH}")
    if not failed.empty:
        print(f"{len(failed)} data quality check(s) FAILED - see outputs/data_quality_report.csv")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
