"""Download member data from unitedstates/congress-legislators.

Both member files are needed: members who left during the 119th Congress
(resignations, deaths, appointments) move to the historical file. The
social media file lists current members' official accounts.

Read from the YAML on the project's main branch, where its data is kept, and
saved as JSON. The JSON copies it publishes on GitHub Pages can fall weeks
behind.
"""

import datetime as dt
import json
import logging

import yaml

from yan.config import RAW_DIR
from yan.http import Client, write_atomic

log = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
FILES = ["legislators-current", "legislators-historical", "legislators-social-media"]


def ingest(client: Client) -> None:
    for name in FILES:
        resp = client.get(f"{BASE_URL}/{name}.yaml")
        resp.raise_for_status()
        content = to_json(resp.content, name)
        write_atomic(RAW_DIR / "legislators" / f"{name}.json", content)
        log.info("legislators: saved %s (%d bytes)", name, len(content))


def to_json(content: bytes, name: str) -> bytes:
    """A YAML file's entries as JSON; raises when it isn't a list with entries."""
    try:
        # The C loader: the Python one takes far longer on the historical file.
        entries = yaml.load(content, Loader=yaml.CSafeLoader)
    except yaml.YAMLError as e:
        raise ValueError(f"legislators: {name} is not valid YAML") from e
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"legislators: {name} is not a list of entries")
    return json.dumps(entries, ensure_ascii=False, default=_date).encode()


def _date(value) -> str:
    """An unquoted date, which YAML reads as a date rather than text."""
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"legislators: unexpected {type(value).__name__} value")
