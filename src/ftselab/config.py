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
# If at least this many stocks show zero volume and an unchanged close on the
# same day, the source has carried prices forward: those rows are removed.
STALE_DAY_MIN_STOCKS = 10
# Maximum share of index trading days a stock may be missing after it starts.
MAX_MISSING_SHARE = 0.02
# Expected range for the number of current constituents.
MIN_CONSTITUENTS, MAX_CONSTITUENTS = 98, 102

# --- Phase 2: risk analytics ----------------------------------------------------------
TRADING_DAYS = 252           # used to annualise daily figures
ROLLING_WINDOW = 252         # one trading year for rolling correlations
ROLLING_MIN_PERIODS = 200    # require most of the year to be present
MIN_HISTORY_YEARS = 3        # stocks with less history are marked short_history

# Stress periods: returns run from the close on base_date to the close on end_date.
STRESS_PERIODS = [
    {
        "period": "covid_crash", "label": "Covid crash",
        "base_date": "2020-02-19", "end_date": "2020-03-23",
        "why": "From the last close before the global sell-off accelerated "
               "(19 Feb 2020) to the FTSE 100's lowest close of 2020 (23 Mar 2020).",
    },
    {
        "period": "hikes_2022", "label": "2022 rate hikes",
        "base_date": "2021-12-31", "end_date": "2022-12-30",
        "why": "Calendar year 2022, in which the MPC raised Bank Rate at 8 meetings, "
               "from 0.25% to 3.5%.",
    },
    {
        "period": "mini_budget", "label": "Sept 2022 mini-budget",
        "base_date": "2022-09-22", "end_date": "2022-10-14",
        "why": "From the close before the 23 Sep 2022 fiscal statement to 14 Oct 2022, "
               "when the Chancellor was replaced and the Bank's emergency gilt buying ended.",
    },
]

# --- Phase 3: event study of Bank Rate decisions ----------------------------------------
# Estimation window for normal returns: trading days -250 to -11 before the event.
EVENT_EST_FIRST = 250
EVENT_EST_LAST = 11
EVENT_MIN_EST_OBS = 150      # events with less estimation data are left out
# Days around every real decision that are kept out of estimation windows and
# out of the placebo pool, so one decision cannot contaminate another.
EVENT_EXCLUDE_BEFORE, EVENT_EXCLUDE_AFTER = 1, 5
# Event windows (first day, last day) relative to the announcement day (day 0).
EVENT_WINDOWS = {"day0": (0, 0), "m1_p1": (-1, 1), "d0_p5": (0, 5)}
EVENT_PATH_DAYS = (-5, 5)    # range of days shown in the average-path chart
PLACEBO_DRAWS = 2000
PLACEBO_WEEKDAY = 3          # Thursday: 156 of 164 decisions fell on a Thursday
RANDOM_SEED = 2026
FDR_LEVEL = 0.10             # Benjamini-Hochberg false discovery rate
EVENT_MIN_EVENTS_STOCK = 5   # stock-level results need at least this many events
