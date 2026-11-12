"""Shared settings: which Congress we track and where data lives on disk."""

from pathlib import Path

CONGRESS = 119
# House Clerk files are organized by calendar year; Senate files by session number.
SESSIONS = {1: 2025, 2: 2026}

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGED_DIR = DATA_DIR / "staged"
OUT_DIR = DATA_DIR / "out"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

# Re-download this many of the most recent votes per session on each run,
# so corrections to the official record are picked up.
REFRESH_RECENT = 20
