"""Download the House and Senate floor schedules (what may come up for a vote).

House: the Majority Leader's weekly floor schedule from docs.house.gov, one XML
file per week, named for that week's Monday. It lists the measures that may be
considered that week, grouped by procedure, without days or times. This week's
and next week's files are fetched on each run; next week's is usually posted
a few days ahead.

Senate: senate.gov publishes no list of upcoming measures. We fetch the session
days (when the Senate met and when it next convenes) and the daily floor
activity for the most recent session days. Its status lines record when a
cloture motion is filed and when cloture is voted on, so the filed motions not
yet voted on are the Senate votes that are coming up.
"""

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import defusedxml.ElementTree as ET
import httpx

from yan.config import CONGRESS, RAW_DIR
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

HOUSE_URL = "https://docs.house.gov/floor/Download.aspx?file=/billsthisweek/{week:%Y%m%d}/{week:%Y%m%d}.xml"
SENATE_DAYS_URL = "https://www.senate.gov/legislative/schedule/floor_schedule.xml"
SENATE_DAY_URL = "https://www.senate.gov/legislative/LIS/floor_activity/{day:%m_%d_%Y}_Senate_Floor.xml"
# Daily floor activity files read for filed cloture motions. A cloture vote
# normally follows its motion within two session days, so ten is ample.
SENATE_RECENT_DAYS = 10
# Re-download this many of the newest daily files, which are updated during the day.
SENATE_REFRESH_DAYS = 2

EASTERN = ZoneInfo("America/New_York")


def house_dir():
    return RAW_DIR / "floor" / "house"


def senate_dir():
    return RAW_DIR / "floor" / "senate"


def today_et() -> dt.date:
    return dt.datetime.now(EASTERN).date()


def week_start(day: dt.date) -> dt.date:
    """The Monday of the week containing `day` (House schedules are named for it)."""
    return day - dt.timedelta(days=day.weekday())


def session_days(content: bytes) -> list[dt.date]:
    """Dates the Senate convened, oldest first, from the session days XML."""
    root = ET.fromstring(content)
    return sorted({
        dt.date.fromisoformat(convene[:10])
        for convene in (s.findtext("ConveneDate") for s in root.iter("SessionDay"))
        if convene
    })


def prune(directory, keep: set[str]) -> None:
    """Delete dated files no longer in the window, so what's on disk is the current schedule."""
    for path in directory.glob("????-??-??.xml"):
        if path.name not in keep:
            path.unlink()


def ingest_house(client: Client, today: dt.date) -> None:
    this_week = week_start(today)
    weeks = (this_week, this_week + dt.timedelta(days=7))
    prune(house_dir(), {f"{week:%Y-%m-%d}.xml" for week in weeks})
    for week in weeks:
        resp = client.get(HOUSE_URL.format(week=week))
        # An unpublished week answers 200 with an HTML error page, or 404.
        if resp.status_code in (200, 404) and b"<floorschedule" not in resp.content:
            log.info("house floor schedule for week of %s: not published", week)
            continue
        resp.raise_for_status()
        if ET.fromstring(resp.content).get("congress-num") != str(CONGRESS):
            raise ValueError(f"House floor schedule for week of {week} is not from the {CONGRESS}th Congress")
        write_atomic(house_dir() / f"{week:%Y-%m-%d}.xml", resp.content)
        log.info("house floor schedule for week of %s: saved", week)


def ingest_senate(client: Client, today: dt.date) -> None:
    resp = client.get(SENATE_DAYS_URL)
    resp.raise_for_status()
    if b"<CongressSessionDayConvenings" not in resp.content:
        raise ValueError("Senate session days: response is not a session day list")
    # Parsed before saving, so a malformed file never reaches the stage step.
    days = [d for d in session_days(resp.content) if d <= today][-SENATE_RECENT_DAYS:]
    write_atomic(senate_dir() / "session_days.xml", resp.content)
    refresh = set(days[-SENATE_REFRESH_DAYS:])
    prune(senate_dir(), {f"{day:%Y-%m-%d}.xml" for day in days})
    saved = 0
    for day in days:
        path = senate_dir() / f"{day:%Y-%m-%d}.xml"
        if path.exists() and day not in refresh:
            continue
        day_resp = client.get(SENATE_DAY_URL.format(day=day))
        # A day not yet posted answers 200 with senate.gov's HTML 404 page.
        if day_resp.status_code in (200, 404) and b"<daily_senate_floor_activity" not in day_resp.content:
            log.info("senate floor activity for %s: not published", day)
            continue
        day_resp.raise_for_status()
        ET.fromstring(day_resp.content)  # raises on a malformed file before it's saved
        write_atomic(path, day_resp.content)
        saved += 1
    log.info("senate floor activity: %d recent session days, %d fetched", len(days), saved)


def ingest(client: Client, today: dt.date | None = None) -> None:
    """Fetch both schedules. A failure is logged, not raised: the schedule is
    secondary, and the hourly run must still publish new votes. The files from
    the last good fetch stay on disk."""
    today = today or today_et()
    for chamber, step in (("house", ingest_house), ("senate", ingest_senate)):
        try:
            step(client, today)
        except (httpx.HTTPError, ValueError, ET.ParseError) as e:
            log.warning("%s floor schedule not updated: %s", chamber, e)
