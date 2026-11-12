"""Download bill details and CRS summaries from the Congress.gov API.

For every bill or resolution with a recorded vote, found by parsing the
House and Senate roll calls already in data/raw/ (so run this after those
ingesters), fetches:

    /bill/{congress}/{type}/{number}            sponsor, cosponsor count, introduced date
    /bill/{congress}/{type}/{number}/summaries  Congressional Research Service summaries

Both change over time (cosponsors are added; CRS writes summaries days to
weeks after each version of a bill), so each file is re-fetched once it's a
week old, and for any bill voted on in the last week. The API key is read from CONGRESS_API_KEY and sent only
in the X-Api-Key header, never in a URL. Without a key this step is skipped.
"""

import datetime as dt
import json
import logging
import os
import time

from yan.config import CONGRESS, RAW_DIR
from yan.http import Client, write_atomic
from yan.measures import parse_measure
from yan.stage import house, senate

log = logging.getLogger(__name__)

API = "https://api.congress.gov/v3"
BILL_URL = API + "/bill/{congress}/{bill_type}/{bill_number}?format=json"
SUMMARIES_URL = API + "/bill/{congress}/{bill_type}/{bill_number}/summaries?format=json"
# Endpoint URL, raw subdirectory, and the key every valid response must have.
ENDPOINTS = [(BILL_URL, "bills", "bill"), (SUMMARIES_URL, "summaries", "summaries")]
REFETCH_AFTER = dt.timedelta(days=7)
RECENT_VOTE_DAYS = 7


def raw_path(bill_type: str, bill_number: str, kind: str = "summaries"):
    return RAW_DIR / "congress_gov" / str(CONGRESS) / kind / f"{bill_type}{bill_number}.json"


def voted_bills() -> dict[tuple[str, str], dt.date]:
    """Every (bill_type, bill_number) with a recorded vote this Congress -> its latest vote date."""
    latest: dict[tuple[str, str], dt.date] = {}
    h_votes, _ = house.parse_dir(RAW_DIR / "house")
    s_votes, _ = senate.parse_dir(RAW_DIR / "senate")
    rows = [(v["legis_num"], dt.datetime.strptime(v["action_date"], "%d-%b-%Y").date()) for v in h_votes]
    rows += [(v["document_name"], dt.datetime.strptime(v["vote_date"], "%B %d, %Y, %I:%M %p").date())
             for v in s_votes]
    for measure, date in rows:
        bill = parse_measure(measure)
        if bill and date > latest.get(bill, dt.date.min):
            latest[bill] = date
    return latest


def needs_fetch(path, last_vote: dt.date, today: dt.date) -> bool:
    if not path.exists():
        return True
    if (today - last_vote).days <= RECENT_VOTE_DAYS:
        return True
    age = dt.timedelta(seconds=time.time() - path.stat().st_mtime)
    return age >= REFETCH_AFTER


def ingest(client: Client) -> None:
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        log.warning("congress.gov: CONGRESS_API_KEY not set; skipping bill details and summaries")
        return

    today = dt.date.today()
    bills = voted_bills()
    fetched = 0
    for (bill_type, bill_number), last_vote in sorted(bills.items()):
        for url_template, kind, required_key in ENDPOINTS:
            path = raw_path(bill_type, bill_number, kind)
            if not needs_fetch(path, last_vote, today):
                continue
            url = url_template.format(congress=CONGRESS, bill_type=bill_type, bill_number=bill_number)
            resp = client.get(url, headers={"X-Api-Key": key})
            resp.raise_for_status()
            if required_key not in resp.json():
                raise ValueError(f"congress.gov {bill_type}{bill_number}: response has no {required_key!r}")
            write_atomic(path, resp.content)
            fetched += 1
    log.info("congress.gov: %d bills with votes, %d files fetched", len(bills), fetched)
