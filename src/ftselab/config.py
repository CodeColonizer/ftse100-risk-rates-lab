"""Project-wide settings: paths, dates, sources and data quality thresholds."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # downloaded files, not committed
REFERENCE_DIR = DATA_DIR / "reference"  # small public reference files, committed
DB_PATH = DATA_DIR / "ftse_lab.db"    # generated SQLite database, not committed
SQL_CLEAN_DIR = ROOT / "sql" / "clean"
OUTPUTS_DIR = ROOT / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"

# Analysis window
START_DATE = "2010-01-01"

# Benchmark: FTSE 100 price index on Yahoo Finance
INDEX_TICKER = "^FTSE"

# --- Sources -----------------------------------------------------------------
WIKIPEDIA_FTSE100_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"

BOE_VOTING_URL = (
    "https://www.bankofengland.co.uk/-/media/boe/files/"
    "monetary-policy-summary-and-minutes/mpcvoting.xlsx"
)
BOE_BANK_RATE_SERIES = "IUDBEDR"  # Official Bank Rate, daily
BOE_IADB_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
    "?csv.x=yes&Datefrom=01/Jan/2009&Dateto=now&SeriesCodes=IUDBEDR"
    "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
)
# The BoE site rejects requests without a browser-like user agent.
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (ftse100-risk-rates-lab data pipeline)"}

# MPC announcements made outside the published schedule (emergency Covid cuts).
UNSCHEDULED_MPC_DATES = {"2020-03-11", "2020-03-19"}

# Exchange rates used to convert lines Yahoo quotes in USD or EUR into pence.
# 'GBPUSD=X' is US dollars per pound.
FX_PAIRS = ["GBPUSD=X", "GBPEUR=X"]

# Reference files (committed)
BOE_DECISIONS_FILE = REFERENCE_DIR / "boe_bank_rate_decisions.csv"
PRICE_CORRECTIONS_FILE = REFERENCE_DIR / "price_corrections.csv"

# --- Data quality thresholds ---------------------------------------------------
# A day-on-day price ratio beyond these bounds looks like a pence/pound (100x)
# unit error rather than a genuine move.
UNIT_RATIO_HIGH = 20.0
UNIT_RATIO_LOW = 1 / 20.0
# Absolute one-day move treated as "extreme" (flagged for review, not removed).
EXTREME_MOVE = 0.25
# "Flat bar" bad print: open = high = low = close, a move bigger than this...
BAD_PRINT_MOVE = 0.15
# ...and the next day brings the price back to within this distance of the
# level before the spike. Genuine volatile days have a real intraday range.
BAD_PRINT_REVERSAL = 0.05
# Maximum share of index trading days a stock may be missing after it starts.
MAX_MISSING_SHARE = 0.02
# Expected range for the number of current constituents.
MIN_CONSTITUENTS, MAX_CONSTITUENTS = 98, 102
