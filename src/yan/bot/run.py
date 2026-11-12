"""Run the bot against data/out/. Dry run only: posts are printed, never published.

    yan bot preview [-n 10] [--vote ID ...]   the N most recent postable votes, ignoring state
    yan bot run                               votes not yet handled per data/bot/state.json
    yan bot init                              mark everything up to the latest vote as handled
"""

import json
from dataclasses import dataclass
from pathlib import Path

from yan.bot import state as bot_state
from yan.bot.format import format_post, grapheme_length
from yan.bot.rules import Decision, decide
from yan.config import OUT_DIR

# STYLE.md pacing: at most one post every ~10 minutes, in order.
POST_INTERVAL_SECONDS = 600


@dataclass
class Candidate:
    vote: dict
    decision: Decision


def load_votes(out_dir: Path = OUT_DIR) -> list[dict]:
    """All votes, oldest first."""
    votes = json.loads((out_dir / "votes.json").read_text())["votes"]
    return sorted(votes, key=lambda v: (v["vote_time_et"], v["chamber"], v["roll_number"]))


def load_vote_doc(vote_id: str, out_dir: Path = OUT_DIR) -> dict:
    return json.loads((out_dir / "votes" / f"{vote_id}.json").read_text())


def render(vote_id: str, out_dir: Path = OUT_DIR) -> tuple[Decision, str | None]:
    doc = load_vote_doc(vote_id, out_dir)
    decision = decide(doc["vote"])
    return decision, (format_post(doc, decision) if decision.post else None)


def print_post(vote: dict, decision: Decision, text: str | None) -> None:
    print(f"--- {vote['vote_id']}  {vote['vote_date']}  [{decision.reason}]")
    if text is None:
        print("(skipped)")
    else:
        print(text)
        print(f"({grapheme_length(text)}/300)")
    print()


def preview(n: int = 10, extra: list[str] | None = None, out_dir: Path = OUT_DIR) -> None:
    votes = load_votes(out_dir)
    postable = [v for v in reversed(votes) if decide(v).post][:n]
    chosen = {v["vote_id"] for v in postable}
    for vote_id in extra or []:
        if vote_id not in chosen:
            postable.append(next(v for v in votes if v["vote_id"] == vote_id))
            chosen.add(vote_id)
    print(f"DRY RUN: {len(postable)} posts (the {n} most recent postable votes"
          f"{' plus ' + ', '.join(extra) if extra else ''}). Nothing is published.\n")
    for vote in postable:
        decision, text = render(vote["vote_id"], out_dir)
        print_post(vote, decision, text)


def pending(state: dict, out_dir: Path = OUT_DIR) -> list[dict]:
    return [v for v in load_votes(out_dir) if bot_state.is_new(v["vote_id"], state[v["chamber"]])]


def run(state_path: Path = bot_state.STATE_PATH, out_dir: Path = OUT_DIR) -> None:
    state = bot_state.load(state_path)
    missing = [c for c, last in state.items() if last is None]
    if missing:
        raise SystemExit(
            f"No bot state for {', '.join(missing)} in {state_path}. Run `yan bot init` to start "
            "from the latest vote; otherwise every vote in the Congress would be queued."
        )
    queue = pending(state, out_dir)
    posts = 0
    print(f"DRY RUN: {len(queue)} new votes since last run. Nothing is published; state is not advanced.\n")
    for vote in queue:
        decision, text = render(vote["vote_id"], out_dir)
        print_post(vote, decision, text)
        posts += decision.post
    if posts > 1:
        print(f"When publishing, these {posts} posts go out in order, one every "
              f"{POST_INTERVAL_SECONDS // 60} minutes.")


def init(state_path: Path = bot_state.STATE_PATH, out_dir: Path = OUT_DIR) -> dict:
    state = {chamber: None for chamber in bot_state.CHAMBERS}
    for vote in load_votes(out_dir):
        chamber = vote["chamber"]
        if bot_state.is_new(vote["vote_id"], state[chamber]):
            state[chamber] = vote["vote_id"]
    bot_state.save(state, state_path)
    return state
