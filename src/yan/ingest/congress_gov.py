"""Download bill details and CRS summaries from the Congress.gov API.

For every bill or resolution with a recorded vote, found by parsing the
House and Senate roll calls already in data/raw/ (so run this after those
ingesters), fetches:

    /bill/{congress}/{type}/{number}            sponsor, cosponsor count, introduced date
    /bill/{congress}/{type}/{number}/summaries  Congressional Research Service summaries
    /bill/{congress}/{type}/{number}/actions    every recorded action (up to 250), newest first

All change over time (cosponsors are added; CRS writes summaries days to
weeks after each version of a bill; actions are added as a bill moves), so
each file is re-fetched once it's a week old, and for any bill voted on in the
last week. Bill files of a Congress that ended more than REFRESH_AFTER_END ago
are fetched only when missing. Missing actions files of bills not voted on in
the last week are fetched at most ACTIONS_BACKFILL_PER_RUN per run.

For every member who served in this Congress, also fetches
/member/{bioguide_id}/sponsored-legislation (every bill and resolution they
introduced, all Congresses, paged) and keeps the items from this Congress.
Re-fetched weekly. Likewise /member/{bioguide_id}/cosponsored-legislation,
which runs to thousands of items (dozens of pages) for long-serving members
and isn't sorted by Congress, so every page is read. A list whose count
changes between its first and last page (a bill added or removed mid-fetch)
is fetched once more. To keep each hourly run
inside the job's timeout, a run fetches cosponsored lists, stalest first, only
until it has used COSPONSORED_REQUEST_BUDGET requests or
COSPONSORED_TIME_BUDGET (the list in progress is finished, so a run can go
over by one list), and fetches none when the process has already run
SKIP_COSPONSORED_AFTER (the weekly sponsored refresh). A list that fails is
logged and skipped, and retried next run. A rate limit (HTTP 429) or
MAX_FAILURES_IN_A_ROW failures in a row stop the run's cosponsored lists early.
If the lists stop after MAX_FAILURES_IN_A_ROW failures with none fetched (not
on a rate limit), the run fails, so a change in the API can't go unnoticed.
Sponsored lists follow the same skip, stop and fail rules, with no budget.

The API key is read from CONGRESS_API_KEY and sent only in the X-Api-Key
header, never in a URL. Without a key this step is skipped.
"""

import datetime as dt
import json
import logging
import os
import time

import httpx

import yan
from yan.config import CONGRESS, CONGRESSES, RAW_DIR, SESSIONS, recently_ended
from yan.http import Client, write_atomic
from yan.measures import parse_measure
from yan.stage import house, legislators, senate

log = logging.getLogger(__name__)

API = "https://api.congress.gov/v3"
BILL_URL = API + "/bill/{congress}/{bill_type}/{bill_number}?format=json"
SUMMARIES_URL = API + "/bill/{congress}/{bill_type}/{bill_number}/summaries?format=json"
ACTIONS_URL = API + "/bill/{congress}/{bill_type}/{bill_number}/actions?format=json&limit=250"
# Endpoint URL, raw subdirectory, and the key every valid response must have.
ENDPOINTS = [(BILL_URL, "bills", "bill"), (SUMMARIES_URL, "summaries", "summaries"),
             (ACTIONS_URL, "actions", "actions")]
# Missing actions files fetched per run for bills not voted on recently, so filling them
# in for every bill at once (one request each) doesn't push a run past its timeout.
ACTIONS_BACKFILL_PER_RUN = 100
MEMBER_LIST_URL = API + "/member/{bioguide_id}/{endpoint}?format=json&limit={limit}&offset={offset}"
PAGE_SIZE = 250  # the API maximum
REFETCH_AFTER = dt.timedelta(days=7)
RECENT_VOTE_DAYS = 7
# Per run, cosponsored lists stop starting once either budget is used. Member-list requests
# take about 2.5-4.6 s each in Actions, so the time budget usually binds first. The first
# fill takes a day or two of hourly runs; then lists refresh weekly.
COSPONSORED_REQUEST_BUDGET = 300
COSPONSORED_TIME_BUDGET = dt.timedelta(minutes=10)
# The weekly sponsored refresh alone takes about 45 minutes; skip cosponsored lists on that
# run so the job stays inside its 75-minute timeout.
SKIP_COSPONSORED_AFTER = dt.timedelta(minutes=30)
# This many member lists failing one after another means the API is down or has
# changed; the rest wait for the next run.
MAX_FAILURES_IN_A_ROW = 3


def raw_path(congress: int, bill_type: str, bill_number: str, kind: str = "summaries"):
    return RAW_DIR / "congress_gov" / str(congress) / kind / f"{bill_type}{bill_number}.json"


def voted_bills() -> dict[tuple[int, str, str], dt.date]:
    """Every (congress, bill_type, bill_number) with a recorded vote -> its latest vote date.
    Bill numbers restart each Congress, so the Congress comes from the vote itself."""
    latest: dict[tuple[int, str, str], dt.date] = {}
    h_votes, _ = house.parse_dir(RAW_DIR / "house")
    s_votes, _ = senate.parse_dir(RAW_DIR / "senate")
    rows = [(v["congress"], v["legis_num"], dt.datetime.strptime(v["action_date"], "%d-%b-%Y").date())
            for v in h_votes]
    rows += [(v["congress"], v["document_name"],
              dt.datetime.strptime(v["vote_date"], "%B %d, %Y, %I:%M %p").date()) for v in s_votes]
    for congress, measure, date in rows:
        bill = parse_measure(measure)
        if bill and date > latest.get(key := (int(congress), *bill), dt.date.min):
            latest[key] = date
    return latest


def members_in_congress() -> list[str]:
    """Bioguide IDs of everyone with a House or Senate term overlapping this Congress.
    A term with no end date is treated as ongoing, and one with no start date as having
    started before this Congress. A date that doesn't parse is logged and treated as
    missing, so one bad row can't stop the ingest or drop a sitting member."""
    start = dt.date(SESSIONS[1], 1, 3)
    end = dt.date(SESSIONS[2] + 1, 1, 3)
    _, terms, _ = legislators.parse_dir(RAW_DIR / "legislators")
    members = set()
    for t in terms:
        term_start = _term_date(t, "term_start", dt.date.min)
        term_end = _term_date(t, "term_end", dt.date.max)
        if term_start < end and term_end > start:
            members.add(t["bioguide_id"])
    return sorted(members)


def _term_date(term: dict, field: str, missing: dt.date) -> dt.date:
    value = term.get(field)
    if not value:
        return missing
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        log.warning("congress.gov: %r has a malformed %s %r; treating it as missing",
                    term["bioguide_id"], field, value)
        return missing


def sponsored_path(bioguide_id: str):
    return RAW_DIR / "congress_gov" / str(CONGRESS) / "sponsored" / f"{bioguide_id}.json"


def cosponsored_path(bioguide_id: str):
    return RAW_DIR / "congress_gov" / str(CONGRESS) / "cosponsored" / f"{bioguide_id}.json"


def fetch_sponsored(client: Client, key: str, bioguide_id: str) -> tuple[dict, int]:
    return fetch_member_list(client, key, bioguide_id, "sponsored")


def fetch_cosponsored(client: Client, key: str, bioguide_id: str) -> tuple[dict, int]:
    return fetch_member_list(client, key, bioguide_id, "cosponsored")


def fetch_member_list(client: Client, key: str, bioguide_id: str, kind: str) -> tuple[dict, int]:
    """Every page of a member's sponsored or cosponsored legislation, keeping this Congress's
    bills and resolutions (amendments, which have no bill type, are dropped), and the
    number of requests it took.

    Pages are by offset, so a bill added or removed mid-fetch shifts the list: an item can
    repeat across a page boundary (repeats are dropped) or be skipped. So if the count on
    the last page differs from the first page's, the list is fetched once more, and that
    second result is kept even if its count changed too (logged). An item that moves
    without changing the count can't be seen this way. An empty page ends the list only
    if that page's count says the list ends there.

    A response that isn't the expected shape raises ValueError. Any error carries the
    number of requests made, the failed one and an earlier pass's included, as `requests`."""
    requests = 0
    try:
        for attempt in (1, 2):
            items, first_count, last_count, made = _fetch_member_list_pages(client, key, bioguide_id, kind)
            requests += made
            if first_count == last_count:
                break
            if attempt == 1:
                log.info("congress.gov member %s: %s list count changed from %d to %d mid-fetch; "
                         "fetching it again", bioguide_id, kind, first_count, last_count)
            else:
                log.warning("congress.gov member %s: %s list count changed from %d to %d again; "
                            "keeping this fetch", bioguide_id, kind, first_count, last_count)
    except Exception as e:
        e.requests = requests + getattr(e, "requests", 0)
        raise
    return {"bioguideId": bioguide_id, "congress": CONGRESS, f"{kind}Legislation": items}, requests


def _fetch_member_list_pages(client: Client, key: str, bioguide_id: str, kind: str) -> tuple[list, int, int, int]:
    """One pass over a member list's pages: (this Congress's items, the first page's count,
    the last page's count, requests made). Errors carry their pass's requests."""
    list_key = f"{kind}Legislation"
    items, seen, offset, total, first_count, requests = [], set(), 0, None, None, 0
    try:
        while total is None or offset < total:
            url = MEMBER_LIST_URL.format(bioguide_id=bioguide_id, endpoint=f"{kind}-legislation",
                                         limit=PAGE_SIZE, offset=offset)
            requests += 1
            resp = client.get(url, headers={"X-Api-Key": key})
            resp.raise_for_status()
            total, page = _member_list_page(resp.json(), list_key, bioguide_id, first=offset == 0)
            if first_count is None:
                first_count = total
            for item in page:
                bill = (item.get("type"), item.get("number"))
                if item.get("congress") == CONGRESS and item.get("type") and bill not in seen:
                    seen.add(bill)
                    items.append(item)
            if not page:
                # Each page's count is current, so a list that shrank between requests
                # ends here; an empty page short of its own count would cut the list short.
                if total > offset:
                    raise ValueError(f"congress.gov member {bioguide_id}: empty page at offset "
                                     f"{offset} of {total}")
                break
            offset += PAGE_SIZE
    except Exception as e:
        e.requests = requests
        raise
    return items, first_count, total, requests


def _member_list_page(doc, list_key: str, bioguide_id: str, first: bool) -> tuple[int, list[dict]]:
    """A member-list response's total item count and its page of items, or ValueError if
    it isn't shaped like one. An empty first page with no pagination is an empty list;
    on a later page, missing pagination could hide a list cut short, so it raises."""
    where = f"congress.gov member {bioguide_id}"
    if not isinstance(doc, dict) or list_key not in doc:
        raise ValueError(f"{where}: response has no {list_key}")
    pagination, page = doc.get("pagination"), doc[list_key]
    if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
        raise ValueError(f"{where}: {list_key} isn't a list of objects")
    if first and pagination is None and not page:
        return 0, page
    count = pagination.get("count") if isinstance(pagination, dict) else None
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError(f"{where}: response has no pagination count")
    return count, page


def needs_fetch(path, last_vote: dt.date, today: dt.date) -> bool:
    if not path.exists():
        return True
    if (today - last_vote).days <= RECENT_VOTE_DAYS:
        return True
    age = dt.timedelta(seconds=time.time() - path.stat().st_mtime)
    return age >= REFETCH_AFTER


def ingest(client: Client, today: dt.date | None = None) -> None:
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        log.warning("congress.gov: CONGRESS_API_KEY not set; skipping bill details and summaries")
        return

    today = today or dt.date.today()
    bills = voted_bills()
    fetched = backfilled = 0
    for (congress, bill_type, bill_number), last_vote in sorted(bills.items()):
        for url_template, kind, required_key in ENDPOINTS:
            path = raw_path(congress, bill_type, bill_number, kind)
            # A Congress not listed (a stray raw file) is treated as long past.
            current = congress == CONGRESS or (congress in CONGRESSES and recently_ended(CONGRESSES[congress], today))
            stale = needs_fetch(path, last_vote, today) if current else not path.exists()
            if not stale:
                continue
            if kind == "actions" and not path.exists() and (today - last_vote).days > RECENT_VOTE_DAYS:
                if backfilled >= ACTIONS_BACKFILL_PER_RUN:
                    continue
                backfilled += 1
            url = url_template.format(congress=congress, bill_type=bill_type, bill_number=bill_number)
            resp = client.get(url, headers={"X-Api-Key": key})
            resp.raise_for_status()
            if required_key not in resp.json():
                raise ValueError(f"congress.gov {bill_type}{bill_number}: response has no {required_key!r}")
            write_atomic(path, resp.content)
            fetched += 1
    log.info("congress.gov: %d bills with votes, %d files fetched", len(bills), fetched)

    members = members_in_congress()
    stale = [m for m in members if needs_fetch(sponsored_path(m), dt.date.min, today)]
    ingest_sponsored(client, key, members, stale)
    ingest_cosponsored(client, key, members, today, yan.STARTED)


def ingest_sponsored(client: Client, key: str, members: list[str], stale: list[str]) -> None:
    """Fetch stale sponsored lists, with no budget."""
    log.info("congress.gov: %d members, %d stale sponsored-legislation lists", len(members), len(stale))
    _fetch_lists(client, key, "sponsored", stale, fetch_sponsored, sponsored_path)


def ingest_cosponsored(client: Client, key: str, members: list[str], today: dt.date, started: float) -> None:
    """Fetch stale cosponsored lists, stalest first (never fetched, then oldest file), so
    lists rotate through the per-run budgets. `started` is when the process began
    (time.monotonic()); the time budget counts from when the cosponsored lists start."""
    stale = sorted(
        (m for m in members if needs_fetch(cosponsored_path(m), dt.date.min, today)),
        key=lambda m: cosponsored_path(m).stat().st_mtime if cosponsored_path(m).exists() else 0,
    )
    if time.monotonic() - started >= SKIP_COSPONSORED_AFTER.total_seconds():
        log.info("congress.gov: skipping %d stale cosponsored-legislation lists this run (process "
                 "already ran %d min)", len(stale), (time.monotonic() - started) // 60)
        return
    deadline = time.monotonic() + COSPONSORED_TIME_BUDGET.total_seconds()
    _fetch_lists(client, key, "cosponsored", stale, fetch_cosponsored, cosponsored_path,
                 within_budget=lambda used: used < COSPONSORED_REQUEST_BUDGET and time.monotonic() < deadline)


def _fetch_lists(client: Client, key: str, kind: str, stale: list[str], fetch, path,
                 within_budget=lambda used: True) -> None:
    """Fetch and save each stale member list in order. `within_budget(requests used so far)`
    is checked before each list starts. A list that fails is logged and skipped (its old
    file kept, retried next run); a rate limit (HTTP 429) or MAX_FAILURES_IN_A_ROW failures
    in a row stop the rest, and stopping that way with none fetched (not on a rate limit)
    raises RuntimeError."""
    used = fetched = failed = in_a_row = 0
    rate_limited = False
    for bioguide_id in stale:
        if not within_budget(used):
            break
        try:
            result = fetch(client, key, bioguide_id)
        except (httpx.HTTPError, ValueError) as e:
            # Log the error type and status only.
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("congress.gov: %s list for %s failed (%s, HTTP %s); skipping",
                        kind, bioguide_id, type(e).__name__, status)
            used += getattr(e, "requests", 1)
            failed += 1
            in_a_row += 1
            rate_limited = status == 429
            if rate_limited or in_a_row >= MAX_FAILURES_IN_A_ROW:
                log.warning("congress.gov: %s; stopping %s lists for this run", "rate limited"
                            if rate_limited else f"{in_a_row} lists failed in a row", kind)
                break
            continue
        # Unpacked outside the try, so a bug here raises instead of reading as an API error.
        doc, requests = result
        write_atomic(path(bioguide_id), json.dumps(doc, sort_keys=True).encode())
        used += requests
        fetched += 1
        in_a_row = 0
    log.info("congress.gov: %d of %d stale %s-legislation lists fetched, %d failed (%d requests)",
             fetched, len(stale), kind, failed, used)
    # A failure or two, or a rate limit, can be a passing outage, and failing the run would
    # hold back the vote posts too; MAX_FAILURES_IN_A_ROW with nothing fetched looks like
    # the API changed.
    if failed >= MAX_FAILURES_IN_A_ROW and not fetched and not rate_limited:
        raise RuntimeError(f"congress.gov: {failed} {kind}-legislation lists failed and none "
                           "were fetched")
