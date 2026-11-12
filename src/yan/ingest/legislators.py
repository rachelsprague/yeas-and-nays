"""Download member data from unitedstates/congress-legislators.

Both files are needed: members who left during the 119th Congress
(resignations, deaths, appointments) move to the historical file.
"""

import logging

from yan.config import RAW_DIR
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

BASE_URL = "https://unitedstates.github.io/congress-legislators"
FILES = ["legislators-current.json", "legislators-historical.json"]


def ingest(client: Client) -> None:
    for name in FILES:
        resp = client.get(f"{BASE_URL}/{name}")
        resp.raise_for_status()
        resp.json()  # fail loudly on a truncated or non-JSON response
        write_atomic(RAW_DIR / "legislators" / name, resp.content)
        log.info("legislators: saved %s (%d bytes)", name, len(resp.content))
