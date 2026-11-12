"""Run the bot against data/out/.

    yan bot preview [-n 10] [--vote ID ...]   the N most recent postable votes, ignoring state
    yan bot run                               dry run: print posts for votes not yet handled
    yan bot run --publish                     post them to Bluesky and advance state
    yan bot init                              mark everything up to the latest vote as handled

Dry runs print only: nothing is published and state is never advanced.
"""

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path

from yan.bot import state as bot_state
from yan.bot.format import format_post, grapheme_length
from yan.bot.rules import Decision, decide
from yan.config import OUT_DIR

# STYLE.md pacing: at most one post every ~10 minutes, in order. A run posts
# at most MAX_POSTS_PER_RUN so it finishes before the next hourly run; any
# remaining votes are picked up then.
POST_INTERVAL_SECONDS = 600
MAX_POSTS_PER_RUN = 5
# Refuse to publish a backlog older than this. Dry runs don't advance state,
# so if publishing is switched on long after `yan bot init`, re-run init
# rather than posting weeks-old votes.
MAX_BACKLOG_AGE = dt.timedelta(days=3)


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


def run(state_path: Path = bot_state.STATE_PATH, out_dir: Path = OUT_DIR, publish: bool = False,
        publisher=None, sleep=time.sleep, today: dt.date | None = None) -> None:
    state = bot_state.load(state_path)
    missing = [c for c, last in state.items() if last is None]
    if missing:
        raise SystemExit(
            f"No bot state for {', '.join(missing)} in {state_path}. Run `yan bot init` to start "
            "from the latest vote; otherwise every vote in the Congress would be queued."
        )
    queue = pending(state, out_dir)
    if not publish:
        _dry_run(queue, out_dir)
        return

    today = today or dt.date.today()
    oldest = min((dt.date.fromisoformat(v["vote_date"]) for v in queue), default=today)
    if today - oldest > MAX_BACKLOG_AGE:
        raise SystemExit(
            f"Refusing to publish: pending votes go back to {oldest}, older than "
            f"{MAX_BACKLOG_AGE.days} days. Run `yan bot init` to start from the latest vote."
        )

    if publisher is None:
        from yan.bot.publish import BlueskyPublisher

        publisher = BlueskyPublisher()
    already_posted = publisher.recent_links()
    print(f"PUBLISHING: {len(queue)} new votes since last run (at most {MAX_POSTS_PER_RUN} posts).\n")
    posts = 0
    for vote in queue:
        decision, text = render(vote["vote_id"], out_dir)
        if text is not None:
            if posts == MAX_POSTS_PER_RUN:
                print("Post limit reached; remaining votes wait for the next run.")
                break
            if text.rsplit("\n", 1)[-1] in already_posted:
                print(f"--- {vote['vote_id']}  already on Bluesky; not posting again\n")
            else:
                if posts:
                    sleep(POST_INTERVAL_SECONDS)
                publisher.post(text, vote["source_url"])
                posts += 1
                print_post(vote, decision, text)
        # Save after every vote handled, so a failure later in the run
        # never causes a repost.
        state[vote["chamber"]] = vote["vote_id"]
        bot_state.save(state, state_path)
    print(f"Published {posts} posts.")


def _dry_run(queue: list[dict], out_dir: Path) -> None:
    posts = 0
    print(f"DRY RUN: {len(queue)} new votes since last run. Nothing is published; state is not advanced.\n")
    for vote in queue:
        decision, text = render(vote["vote_id"], out_dir)
        print_post(vote, decision, text)
        posts += decision.post
    if posts > 1:
        print(f"When publishing, these {posts} posts go out in order, one every "
              f"{POST_INTERVAL_SECONDS // 60} minutes, at most {MAX_POSTS_PER_RUN} per run.")


def init(state_path: Path = bot_state.STATE_PATH, out_dir: Path = OUT_DIR) -> dict:
    state = {chamber: None for chamber in bot_state.CHAMBERS}
    for vote in load_votes(out_dir):
        chamber = vote["chamber"]
        if bot_state.is_new(vote["vote_id"], state[chamber]):
            state[chamber] = vote["vote_id"]
    bot_state.save(state, state_path)
    return state
