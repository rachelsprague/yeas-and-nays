"""Download Senate roll call XML from senate.gov.

The vote menu for each session lists every vote number; each vote has its own
XML file. Votes already on disk are skipped, except the most recent few, which
are re-fetched to pick up corrections.
"""

import logging

import defusedxml.ElementTree as ET

from yan.config import CONGRESS, RAW_DIR, REFRESH_RECENT, SESSIONS
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

BASE = "https://www.senate.gov/legislative/LIS"
MENU_URL = BASE + "/roll_call_lists/vote_menu_{congress}_{session}.xml"
VOTE_URL = BASE + "/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{vote:05d}.xml"


def raw_dir(session: int):
    return RAW_DIR / "senate" / str(CONGRESS) / str(session)


def raw_path(session: int, vote: int):
    return raw_dir(session) / f"vote_{CONGRESS}_{session}_{vote:05d}.xml"


def vote_numbers_from_menu(content: bytes) -> list[int]:
    root = ET.fromstring(content)
    return sorted(int(v.findtext("vote_number")) for v in root.iter("vote"))


def ingest(client: Client, sessions: list[int] | None = None) -> None:
    for session in sessions or SESSIONS:
        resp = client.get(MENU_URL.format(congress=CONGRESS, session=session))
        if resp.status_code == 404:
            log.info("senate session %d: no vote menu yet", session)
            continue
        resp.raise_for_status()
        numbers = vote_numbers_from_menu(resp.content)
        write_atomic(raw_dir(session) / "vote_menu.xml", resp.content)

        recent = set(numbers[-REFRESH_RECENT:])
        todo = [n for n in numbers if n in recent or not raw_path(session, n).exists()]
        for n in todo:
            vote = client.get(VOTE_URL.format(congress=CONGRESS, session=session, vote=n))
            vote.raise_for_status()
            if b"<roll_call_vote" not in vote.content:
                raise ValueError(f"Senate session {session} vote {n}: response is not a roll call vote")
            write_atomic(raw_path(session, n), vote.content)
        log.info("senate session %d: %d votes listed, %d fetched", session, len(numbers), len(todo))
