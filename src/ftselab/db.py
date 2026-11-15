"""SQLite database with a raw layer (as downloaded) and a clean layer (sql/clean/)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from . import config

SQL_TOKENS = {
    "UNIT_RATIO_HIGH": config.UNIT_RATIO_HIGH,
    "UNIT_RATIO_LOW": config.UNIT_RATIO_LOW,
    "EXTREME_MOVE": config.EXTREME_MOVE,
    "BAD_PRINT_MOVE": config.BAD_PRINT_MOVE,
    "BAD_PRINT_REVERSAL": config.BAD_PRINT_REVERSAL,
}


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def load_raw(conn: sqlite3.Connection, tables: dict[str, pd.DataFrame]) -> None:
    """Replace each raw_<name> table with the given frame, unchanged."""
    for name, frame in tables.items():
        frame.to_sql(f"raw_{name}", conn, if_exists="replace", index=False)
    if "prices" in tables:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_raw_prices ON raw_prices (ticker, date)")
    if "bank_rate_daily" in tables:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_raw_bank_rate ON raw_bank_rate_daily (date)")
    if "fx" in tables:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_raw_fx ON raw_fx (pair, date)")
    conn.commit()


def render_sql(text: str, tokens: dict[str, float] = SQL_TOKENS) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", repr(float(value)))
    if "{{" in text:
        raise ValueError("Unreplaced token in SQL")
    return text


def build_clean(conn: sqlite3.Connection, sql_dir: Path = config.SQL_CLEAN_DIR) -> list[str]:
    """Run every clean-layer SQL file in name order. Returns the files run."""
    files = sorted(sql_dir.glob("*.sql"))
    for f in files:
        conn.executescript(render_sql(f.read_text(encoding="utf-8")))
    conn.commit()
    return [f.name for f in files]


def query(sql: str, conn: sqlite3.Connection | None = None, **params) -> pd.DataFrame:
    """Convenience helper for analysis code and tests."""
    own = conn is None
    conn = conn or connect()
    try:
        return pd.read_sql_query(sql, conn, params=params or None)
    finally:
        if own:
            conn.close()
