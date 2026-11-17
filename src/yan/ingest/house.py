"""Download House roll call XML from the Office of the Clerk.

The Clerk publishes one file per vote at clerk.house.gov/evs/{year}/rollNNN.xml
and has no machine-readable index. Requests past the last vote return HTTP 200
with a short error body rather than a 404, so we walk roll numbers upward and
stop when a response doesn't contain a vote.

For the Congress in session, the most recent votes are re-fetched each run to
pick up corrections. A past Congress's files only get walked on from the last
one on disk, so a run costs a couple of requests per year, and a lost cache
refills.
"""

import logging
import re

from yan.config import CONGRESS, CONGRESSES, RAW_DIR, REFRESH_RECENT
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

URL = "https://clerk.house.gov/evs/{year}/roll{roll:03d}.xml"
# Stop after this many consecutive missing roll numbers, to ride out a
# single transient error without walking off the end forever.
MAX_CONSECUTIVE_MISSES = 2


def raw_dir(year: int):
    return RAW_DIR / "house" / str(year)


def raw_path(year: int, roll: int):
    return raw_dir(year) / f"roll{roll:03d}.xml"


def is_vote(content: bytes) -> bool:
    return b"<rollcall-vote" in content


def existing_rolls(year: int) -> list[int]:
    return sorted(
        int(m.group(1))
        for p in raw_dir(year).glob("roll*.xml")
        if (m := re.fullmatch(r"roll(\d+)\.xml", p.name))
    )


def ingest(client: Client, congresses: dict[int, dict[int, int]] | None = None) -> None:
    for congress, sessions in (congresses or CONGRESSES).items():
        refresh = REFRESH_RECENT if congress == CONGRESS else 0
        for year in sessions.values():
            ingest_year(client, congress, year, refresh)


def ingest_year(client: Client, congress: int, year: int, refresh: int) -> None:
    have = existing_rolls(year)
    roll = max(1, (have[-1] - refresh + 1) if have else 1)
    misses, saved = 0, 0
    while misses < MAX_CONSECUTIVE_MISSES:
        resp = client.get(URL.format(year=year, roll=roll))
        if resp.status_code == 200 and is_vote(resp.content):
            if f"<congress>{congress}</congress>".encode() not in resp.content:
                raise ValueError(f"House {year} roll {roll} is not from the {congress}th Congress")
            write_atomic(raw_path(year, roll), resp.content)
            saved += 1
            misses = 0
        elif resp.status_code in (200, 404):
            misses += 1
        else:
            resp.raise_for_status()
        roll += 1
    log.info("house %d: saved %d votes (through roll %d)", year, saved, roll - 1 - misses)
