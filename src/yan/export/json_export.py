"""Export the dbt marts to small, deterministic JSON files under data/out/.

    data/out/meta.json            congress, counts, latest roll number per chamber/session
    data/out/members.json         one entry per member, with their stats this Congress
    data/out/votes.json           one entry per vote (metadata + tallies), newest first
    data/out/votes/{vote_id}.json one vote: metadata, party totals, caucus majorities,
                                  members who voted against their party majority,
                                  and every member's position as recorded

Output is a pure function of the warehouse: keys are sorted, each list
element sits on its own line, and nothing time-of-run is written. A re-run
with no new data produces no git diff.
"""

import datetime as dt
import json
import logging
from collections import defaultdict
from pathlib import Path

import duckdb

from yan.bot.rules import measure_label
from yan.config import CONGRESS, OUT_DIR, WAREHOUSE_PATH

log = logging.getLogger(__name__)

VOTE_ORDER = "vote_time_et desc, chamber, roll_number desc"


def _default(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _compact(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def dumps(document: dict) -> str:
    """Render a top-level object with one key per line and one list element per line."""
    lines = []
    for key in sorted(document):
        value = document[key]
        if isinstance(value, list) and value:
            inner = ",\n".join("    " + _compact(item) for item in value)
            lines.append(f"  {json.dumps(key)}: [\n{inner}\n  ]")
        else:
            lines.append(f"  {json.dumps(key)}: {_compact(value)}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def _rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run(warehouse: Path = WAREHOUSE_PATH, out_dir: Path = OUT_DIR) -> None:
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        members = _rows(con, """
            select members.*, stats.* exclude (bioguide_id)
            from members
            left join member_stats as stats using (bioguide_id)
            order by bioguide_id
        """)
        votes = [with_measure_label(v) for v in _rows(con, f"select * from votes order by {VOTE_ORDER}")]
        positions = _rows(con, """
            select vote_id, bioguide_id, member_label, party, caucus_party, position_raw,
                   position, caucus_majority_position, voted_against_party_majority
            from positions
            order by vote_id, member_label, bioguide_id
        """)
    finally:
        con.close()

    by_vote = defaultdict(list)
    for p in positions:
        by_vote[p["vote_id"]].append(p)

    changed = 0
    changed += write_if_changed(out_dir / "members.json", dumps({"congress": CONGRESS, "members": members}))
    changed += write_if_changed(out_dir / "votes.json", dumps({"congress": CONGRESS, "votes": votes}))

    vote_dir = out_dir / "votes"
    expected = set()
    for vote in votes:
        name = f"{vote['vote_id']}.json"
        expected.add(name)
        changed += write_if_changed(vote_dir / name, dumps(vote_document(vote, by_vote[vote["vote_id"]])))

    # Remove files for votes no longer in the warehouse.
    for path in vote_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
            changed += 1

    changed += write_if_changed(out_dir / "meta.json", dumps(meta_document(votes, members)))
    log.info("export: %d votes, %d members, %d files changed", len(votes), len(members), changed)


def with_measure_label(vote: dict) -> dict:
    """Add the measure number in citation form ("H RES 1655" -> "H.Res. 1655") for display."""
    return {**vote, "measure_label": measure_label(vote)}


def vote_document(vote: dict, positions: list[dict]) -> dict:
    party_totals = defaultdict(lambda: defaultdict(int))
    caucus_majority = {}
    against = []
    for p in positions:
        party_totals[p["party"]][p["position"]] += 1
        caucus_majority[p["caucus_party"]] = p["caucus_majority_position"]
        if p["voted_against_party_majority"]:
            against.append({
                "bioguide_id": p["bioguide_id"],
                "member_label": p["member_label"],
                "position": p["position_raw"],
            })
    return {
        "vote": vote,
        "party_totals": {party: dict(counts) for party, counts in party_totals.items()},
        "caucus_majority_position": caucus_majority,
        "against_party_majority": against,
        "positions": {p["bioguide_id"]: p["position_raw"] for p in positions},
    }


def meta_document(votes: list[dict], members: list[dict]) -> dict:
    latest = defaultdict(dict)
    for v in votes:
        key = str(v["session"])
        latest[v["chamber"]][key] = max(latest[v["chamber"]].get(key, 0), v["roll_number"])
    return {
        "congress": CONGRESS,
        "vote_count": len(votes),
        "member_count": len(members),
        "latest_vote_date": max((v["vote_date"] for v in votes), default=None),
        "latest_roll_number": latest,
    }
