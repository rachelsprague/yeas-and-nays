"""Download the Congressional Directory from GovInfo, for members' biographies.

The Joint Committee on Printing publishes the directory a few times a Congress
(GovInfo collection CDIR); each edition has a biography of every member,
furnished or authorized by the member's office. This step lists the editions
issued in the last LOOKBACK and saves the newest one's plain text as
data/raw/directory/{package ID}.txt, removing older editions' files. The list
is checked once its saved copy (editions.json) is REFETCH_AFTER old, so a new
edition shows up within a week.

GovInfo takes an api.data.gov key, the same kind as the Congress.gov API's, so
this reads CONGRESS_API_KEY and sends it only in the X-Api-Key header. Without a
key this step is skipped. A failed request or an edition with fewer than
MIN_BIOS biographies is logged as an error and leaves the saved edition in
place, so the hourly votes aren't held up by a weekly bio refresh; the dbt test
`members_without_bios` warns when bios go missing. It is tried again once
RETRY_AFTER has passed (the time is kept in the `failed` file), rather than
downloading the full text every hour.
"""

import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from yan.config import RAW_DIR
from yan.http import Client, write_atomic
from yan.stage import directory

log = logging.getLogger(__name__)

API = "https://api.govinfo.gov"
EDITIONS_URL = API + "/published/{start}?collection=CDIR&offsetMark=*&pageSize=100"
TEXT_URL = API + "/packages/{package_id}/txt"
# Editions come out every year or two; three years back always includes the newest one.
LOOKBACK = dt.timedelta(days=3 * 365)
REFETCH_AFTER = dt.timedelta(days=7)
RETRY_AFTER = dt.timedelta(days=1)
# The 2026 edition has 500; a file with far fewer has changed format or been cut short.
MIN_BIOS = 400
DIR = RAW_DIR / "directory"
PACKAGE_ID = re.compile(r"CDIR-\d{4}-\d{2}-\d{2}")


def ingest(client: Client, today: dt.date | None = None) -> None:
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        log.warning("directory: CONGRESS_API_KEY not set; skipping")
        return
    failed = DIR / "failed"
    if newer_than(DIR / "editions.json", REFETCH_AFTER) or newer_than(failed, RETRY_AFTER):
        return
    try:
        fetch(client, key, today or dt.date.today())
    except (httpx.HTTPError, ValueError) as e:
        log.error("directory: %s; keeping the saved edition", e)
        write_atomic(failed, b"")
    else:
        failed.unlink(missing_ok=True)


def newer_than(path: Path, age: dt.timedelta) -> bool:
    return path.exists() and time.time() - path.stat().st_mtime < age.total_seconds()


def fetch(client: Client, key: str, today: dt.date) -> None:
    resp = client.get(EDITIONS_URL.format(start=(today - LOOKBACK).isoformat()), headers={"X-Api-Key": key})
    resp.raise_for_status()
    packages = resp.json().get("packages")
    if not isinstance(packages, list):
        raise ValueError("GovInfo editions list has no 'packages'")
    newest = newest_edition(packages)
    if newest is None:
        raise ValueError(f"no Congressional Directory issued since {today - LOOKBACK}")

    path = DIR / f"{newest}.txt"
    if not path.exists():
        resp = client.get(TEXT_URL.format(package_id=newest), headers={"X-Api-Key": key})
        resp.raise_for_status()
        # Decoded the way stage reads the saved file.
        if (n := len(directory.parse(resp.content.decode("utf-8")))) < MIN_BIOS:
            raise ValueError(f"{newest} has {n} biographies (expected at least {MIN_BIOS})")
        write_atomic(path, resp.content)
        log.info("directory: saved %s (%d bytes)", path.name, len(resp.content))
        for old in DIR.glob("*.txt"):
            if old != path:
                old.unlink()
    write_atomic(DIR / "editions.json", json.dumps(packages, sort_keys=True).encode())


def newest_edition(packages: list) -> str | None:
    """The package ID of the edition issued last, or None if there is none. An ID not in
    the form CDIR-YYYY-MM-DD is skipped: it goes into a URL and a file name."""
    editions = [p for p in packages if isinstance(p, dict) and isinstance(p.get("packageId"), str)
                and PACKAGE_ID.fullmatch(p["packageId"]) and isinstance(p.get("dateIssued"), str)]
    return max(editions, key=lambda p: (p["dateIssued"], p["packageId"]))["packageId"] if editions else None
