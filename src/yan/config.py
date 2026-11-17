"""Shared settings: which Congresses we track and where data lives on disk."""

import datetime as dt
from pathlib import Path

# The Congress in session: the bot posts its votes and ingest refreshes its recent files.
CONGRESS = 119
# Every Congress on the site, each session -> its calendar year. House Clerk files are
# organized by calendar year; Senate files by session number. Past Congresses stay on
# the site; once REFRESH_AFTER_END has passed since one ended, ingest re-fetches its
# files only when they're missing (a lost cache). Keep transform/seeds/congresses.csv
# (and dbt's `congress` var, for CONGRESS) in step; tests/test_congresses_seed.py checks.
CONGRESSES = {119: {1: 2025, 2: 2026}}
SESSIONS = CONGRESSES[CONGRESS]
# A Congress that just ended is still refreshed like the one in session for this long:
# its last votes can come hours before it ends, and CRS summaries and cosponsors of
# the bills it voted on keep arriving for weeks after.
REFRESH_AFTER_END = dt.timedelta(days=60)
SITE_URL = "https://yeasandnaysdata.com"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGED_DIR = DATA_DIR / "staged"
OUT_DIR = DATA_DIR / "out"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

# Re-download this many of the most recent votes per session on each run,
# so corrections to the official record are picked up.
REFRESH_RECENT = 20


def recently_ended(sessions: dict[int, int], today: dt.date) -> bool:
    """Whether a Congress with these sessions (session -> year) ended, or ends, less than
    REFRESH_AFTER_END before `today`. A Congress ends on Jan. 3 after its last session's year."""
    return today < dt.date(max(sessions.values()) + 1, 1, 3) + REFRESH_AFTER_END
