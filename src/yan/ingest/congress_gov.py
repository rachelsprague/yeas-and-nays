"""Download bill details and CRS summaries from the Congress.gov API.

For every bill or resolution with a recorded vote, found by parsing the
House and Senate roll calls already in data/raw/ (so run this after those
ingesters), fetches:

    /bill/{congress}/{type}/{number}            sponsor, cosponsor count, introduced date
    /bill/{congress}/{type}/{number}/summaries  Congressional Research Service summaries

Both change over time (cosponsors are added; CRS writes summaries days to
weeks after each version of a bill), so each file is re-fetched once it's a
week old, and for any bill voted on in the last week.

For every member who served in this Congress, also fetches
/member/{bioguide_id}/sponsored-legislation (every bill and resolution they
introduced, all Congresses, paged) and keeps the items from this Congress.
Re-fetched weekly. Likewise /member/{bioguide_id}/cosponsored-legislation,
which runs to thousands of items (dozens of pages) for long-serving members
and isn't sorted by Congress, so every page is read; to keep each hourly run
short, at most COSPONSORED_REQUEST_BUDGET requests go to it per run, stalest
lists first. The API key is read from CONGRESS_API_KEY and sent only
in the X-Api-Key header, never in a URL. Without a key this step is skipped.
"""

import datetime as dt
import json
import logging
import os
import time

from yan.config import CONGRESS, RAW_DIR, SESSIONS
from yan.http import Client, write_atomic
from yan.measures import parse_measure
from yan.stage import house, legislators, senate

log = logging.getLogger(__name__)

API = "https://api.congress.gov/v3"
BILL_URL = API + "/bill/{congress}/{bill_type}/{bill_number}?format=json"
SUMMARIES_URL = API + "/bill/{congress}/{bill_type}/{bill_number}/summaries?format=json"
# Endpoint URL, raw subdirectory, and the key every valid response must have.
ENDPOINTS = [(BILL_URL, "bills", "bill"), (SUMMARIES_URL, "summaries", "summaries")]
MEMBER_LIST_URL = API + "/member/{bioguide_id}/{endpoint}?format=json&limit={limit}&offset={offset}"
PAGE_SIZE = 250  # the API maximum
REFETCH_AFTER = dt.timedelta(days=7)
RECENT_VOTE_DAYS = 7
# Requests per run for cosponsored lists: about 10 minutes, and well under the API's
# 5,000 an hour. The first fill takes a day or so of hourly runs; then lists refresh weekly.
COSPONSORED_REQUEST_BUDGET = 300


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


def members_in_congress() -> list[str]:
    """Bioguide IDs of everyone with a House or Senate term overlapping this Congress."""
    start = dt.date(SESSIONS[1], 1, 3)
    _, terms, _ = legislators.parse_dir(RAW_DIR / "legislators")
    return sorted({t["bioguide_id"] for t in terms if t["term_end"] and dt.date.fromisoformat(t["term_end"]) > start})


def sponsored_path(bioguide_id: str):
    return RAW_DIR / "congress_gov" / str(CONGRESS) / "sponsored" / f"{bioguide_id}.json"


def cosponsored_path(bioguide_id: str):
    return RAW_DIR / "congress_gov" / str(CONGRESS) / "cosponsored" / f"{bioguide_id}.json"


def fetch_sponsored(client: Client, key: str, bioguide_id: str) -> dict:
    return fetch_member_list(client, key, bioguide_id, "sponsored")[0]


def fetch_cosponsored(client: Client, key: str, bioguide_id: str) -> tuple[dict, int]:
    return fetch_member_list(client, key, bioguide_id, "cosponsored")


def fetch_member_list(client: Client, key: str, bioguide_id: str, kind: str) -> tuple[dict, int]:
    """Every page of a member's sponsored or cosponsored legislation, keeping this Congress's
    bills and resolutions (amendments, which have no bill type, are dropped), and the
    number of requests it took.

    Pages are by offset, so a bill introduced mid-fetch shifts the list and can
    repeat one item across a page boundary; repeats are dropped."""
    list_key = f"{kind}Legislation"
    items, seen, offset, total, requests = [], set(), 0, None, 0
    while total is None or offset < total:
        url = MEMBER_LIST_URL.format(bioguide_id=bioguide_id, endpoint=f"{kind}-legislation",
                                     limit=PAGE_SIZE, offset=offset)
        resp = client.get(url, headers={"X-Api-Key": key})
        requests += 1
        resp.raise_for_status()
        doc = resp.json()
        if list_key not in doc:
            raise ValueError(f"congress.gov member {bioguide_id}: response has no {list_key}")
        total = doc.get("pagination", {}).get("count", 0)
        page = doc[list_key]
        for item in page:
            bill = (item.get("type"), item.get("number"))
            if item.get("congress") == CONGRESS and item.get("type") and bill not in seen:
                seen.add(bill)
                items.append(item)
        if not page:
            break
        offset += PAGE_SIZE
    return {"bioguideId": bioguide_id, "congress": CONGRESS, list_key: items}, requests


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

    members = members_in_congress()
    stale = [m for m in members if needs_fetch(sponsored_path(m), dt.date.min, today)]
    for bioguide_id in stale:
        doc = fetch_sponsored(client, key, bioguide_id)
        write_atomic(sponsored_path(bioguide_id), json.dumps(doc, sort_keys=True).encode())
    log.info("congress.gov: %d members, %d sponsored-legislation lists fetched", len(members), len(stale))

    # Stalest first (never fetched, then oldest file), so lists rotate through the budget.
    stale = sorted(
        (m for m in members if needs_fetch(cosponsored_path(m), dt.date.min, today)),
        key=lambda m: cosponsored_path(m).stat().st_mtime if cosponsored_path(m).exists() else 0,
    )
    used = fetched = 0
    for bioguide_id in stale:
        if used >= COSPONSORED_REQUEST_BUDGET:
            break
        doc, requests = fetch_cosponsored(client, key, bioguide_id)
        write_atomic(cosponsored_path(bioguide_id), json.dumps(doc, sort_keys=True).encode())
        used += requests
        fetched += 1
    log.info("congress.gov: %d of %d stale cosponsored-legislation lists fetched (%d requests)",
             fetched, len(stale), used)
