"""Download Senate roll call XML from senate.gov.

The vote menu for each session lists every vote number; each vote has its own
XML file. Votes already on disk are skipped, except the most recent few, which
are re-fetched to pick up corrections. For a Congress that ended more than
REFRESH_AFTER_END ago, the menu saved on disk is used and only missing votes
are fetched, so a run makes no requests unless the cache was lost.
"""

import datetime as dt
import logging

import defusedxml.ElementTree as ET

from yan.config import CONGRESS, CONGRESSES, RAW_DIR, REFRESH_RECENT, recently_ended
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

BASE = "https://www.senate.gov/legislative/LIS"
MENU_URL = BASE + "/roll_call_lists/vote_menu_{congress}_{session}.xml"
VOTE_URL = BASE + "/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{vote:05d}.xml"


def raw_dir(congress: int, session: int):
    return RAW_DIR / "senate" / str(congress) / str(session)


def raw_path(congress: int, session: int, vote: int):
    return raw_dir(congress, session) / f"vote_{congress}_{session}_{vote:05d}.xml"


def vote_numbers_from_menu(content: bytes) -> list[int]:
    root = ET.fromstring(content)
    return sorted(int(v.findtext("vote_number")) for v in root.iter("vote"))


def ingest(client: Client, congresses: dict[int, dict[int, int]] | None = None,
           today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    for congress, sessions in (congresses or CONGRESSES).items():
        current = congress == CONGRESS or recently_ended(sessions, today)
        for session in sessions:
            ingest_session(client, congress, session, current)


def ingest_session(client: Client, congress: int, session: int, current: bool) -> None:
    menu = raw_dir(congress, session) / "vote_menu.xml"
    if not current and menu.exists():
        numbers = vote_numbers_from_menu(menu.read_bytes())
    else:
        resp = client.get(MENU_URL.format(congress=congress, session=session))
        if resp.status_code == 404:
            log.info("senate %d session %d: no vote menu yet", congress, session)
            return
        resp.raise_for_status()
        numbers = vote_numbers_from_menu(resp.content)
        write_atomic(menu, resp.content)

    recent = set(numbers[-REFRESH_RECENT:]) if current else set()
    todo = [n for n in numbers if n in recent or not raw_path(congress, session, n).exists()]
    for n in todo:
        vote = client.get(VOTE_URL.format(congress=congress, session=session, vote=n))
        vote.raise_for_status()
        if b"<roll_call_vote" not in vote.content:
            raise ValueError(f"Senate {congress} session {session} vote {n}: response is not a roll call vote")
        write_atomic(raw_path(congress, session, n), vote.content)
    log.info("senate %d session %d: %d votes listed, %d fetched", congress, session, len(numbers), len(todo))
