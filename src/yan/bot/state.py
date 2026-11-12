"""Bot state: the last vote handled per chamber, committed to the repo so runs
are idempotent. A vote is "handled" once it has been posted or skipped by the
post rules, so nothing is posted twice and later corrections to an old vote
don't trigger a repost (STYLE.md pacing rules)."""

import json
from pathlib import Path

from yan.config import DATA_DIR

STATE_PATH = DATA_DIR / "bot" / "state.json"
CHAMBERS = ("house", "senate")


def vote_order(vote_id: str) -> tuple[int, int, int]:
    """Sort key for a vote ID like h119-2-0317: (congress, session, roll)."""
    congress, session, roll = vote_id[1:].split("-")
    return int(congress), int(session), int(roll)


def load(path: Path = STATE_PATH) -> dict[str, str | None]:
    if not path.exists():
        return {chamber: None for chamber in CHAMBERS}
    data = json.loads(path.read_text())
    return {chamber: data.get(chamber, {}).get("last_vote_id") for chamber in CHAMBERS}


def save(state: dict[str, str | None], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {chamber: {"last_vote_id": state[chamber]} for chamber in CHAMBERS}
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def is_new(vote_id: str, chamber_state: str | None) -> bool:
    return chamber_state is None or vote_order(vote_id) > vote_order(chamber_state)
