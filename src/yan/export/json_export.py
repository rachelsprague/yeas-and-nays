"""Export the dbt marts to small, deterministic JSON files under data/out/.

    data/out/meta.json            congress, counts, latest roll number per chamber/session
    data/out/members.json         one entry per member, with their stats this Congress
    data/out/members/{bioguide}.json  one member: bills and resolutions they introduced
                                  and cosponsored this Congress, newest first
                                  (cosponsored is null until first fetched)
    data/out/floor_schedule.json  what may come up for a vote: the House's weekly
                                  floor schedule and pending Senate cloture motions,
                                  plus when the Senate next convenes
    data/out/votes.json           one entry per vote (metadata + tallies), newest first
    data/out/votes/{vote_id}.json one vote: metadata, party totals, caucus majorities,
                                  members who voted against their party majority,
                                  every member's position as recorded, and the CRS
                                  summary of the measure, when there is one

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
from yan.export import summary_html
from yan.measures import bill_label

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
        sponsored = _rows(con, """
            select bioguide_id, bill_id, bill_type, bill_number, title, introduced_date,
                   latest_action_date, latest_action_text, policy_area, congress_gov_url,
                   latest_vote_id
            from sponsored_bills
            order by bioguide_id, introduced_date desc, bill_type, try_cast(bill_number as integer) desc
        """)
        cosponsored = _rows(con, """
            select bioguide_id, bill_id, bill_type, bill_number, title, introduced_date,
                   latest_action_date, latest_action_text, policy_area, congress_gov_url,
                   latest_vote_id
            from cosponsored_bills
            order by bioguide_id, introduced_date desc, bill_type, try_cast(bill_number as integer) desc
        """)
        cosponsored_fetched = {row["bioguide_id"] for row in _rows(con, "select bioguide_id from cosponsored_lists")}
        floor_items = _rows(con, """
            select chamber, item_id, week_date, filed_date, category, question, measure_number,
                   bill_type, bill_number, title, amends, congress_gov_url, vote_id
            from floor_schedule
            order by chamber, week_date, category_order, item_order, filed_date,
                -- Numbers in numeric order: PN1272-3 before PN1272-13.
                regexp_extract(measure_number, '^\\D*'),
                try_cast(regexp_extract(measure_number, '(\\d+)', 1) as integer),
                try_cast(regexp_extract(measure_number, '-(\\d+)', 1) as integer),
                item_id
        """)
        senate_sessions = _rows(con, """
            select convene_time_et, adjourn_time_et, next_convene_time_et
            from senate_sessions
            order by convene_time_et
        """)
        summaries = {
            row.pop("vote_id"): row
            for row in _rows(con, """
                select vote_id, version_code, action_date, action_desc, summary_html
                from vote_summaries
            """)
        }
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
        doc = vote_document(vote, by_vote[vote["vote_id"]], summaries.get(vote["vote_id"]))
        changed += write_if_changed(vote_dir / name, dumps(doc))

    # Remove files for votes no longer in the warehouse.
    for path in vote_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
            changed += 1

    sponsored_by, cosponsored_by = defaultdict(list), defaultdict(list)
    for bills, by_member in ((sponsored, sponsored_by), (cosponsored, cosponsored_by)):
        for bill in bills:
            bill["measure_label"] = bill_label(bill["bill_type"], bill["bill_number"])
            by_member[bill.pop("bioguide_id")].append(bill)
    member_dir = out_dir / "members"
    expected = set()
    for member in members:
        name = f"{member['bioguide_id']}.json"
        expected.add(name)
        bioguide_id = member["bioguide_id"]
        doc = {
            "bioguide_id": bioguide_id,
            "sponsored": sponsored_by[bioguide_id],
            # Null until the member's cosponsored list is first fetched (lists fill in over
            # several runs), so the site can leave the section out rather than show none.
            "cosponsored": cosponsored_by[bioguide_id] if bioguide_id in cosponsored_fetched else None,
        }
        changed += write_if_changed(member_dir / name, dumps(doc))
    for path in member_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
            changed += 1

    changed += write_if_changed(
        out_dir / "floor_schedule.json", dumps(floor_schedule_document(floor_items, senate_sessions))
    )

    meta = meta_document(votes, members)
    # False when Congress.gov sponsored lists weren't ingested (e.g. no API key), so the
    # site can hide the section instead of showing every member with no bills.
    meta["has_sponsored_bills"] = bool(sponsored)
    changed += write_if_changed(out_dir / "meta.json", dumps(meta))
    log.info("export: %d votes, %d members, %d files changed", len(votes), len(members), changed)


def with_measure_label(vote: dict) -> dict:
    """Add the measure number in citation form ("H RES 1655" -> "H.Res. 1655") for display."""
    return {**vote, "measure_label": measure_label(vote)}


def summary_document(summary: dict | None) -> dict | None:
    """The CRS summary for a vote's measure, its HTML reduced to formatting tags."""
    if not summary or not (html := summary_html.clean(summary["summary_html"])):
        return None
    return {
        "html": html,
        "version": summary["action_desc"],
        "version_date": summary["action_date"],
        "version_code": summary["version_code"],
    }


def vote_document(vote: dict, positions: list[dict], summary: dict | None = None) -> dict:
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
        "summary": summary_document(summary),
    }


def floor_schedule_document(items: list[dict], senate_sessions: list[dict]) -> dict:
    """Floor schedule items with a display label, and when the Senate is next set to convene.

    The label is the citation form for bills and resolutions ("H.Res. 1650"), else
    the number as listed ("PN1272-3", "H. Res. ___"); amendments name what they amend.
    """
    for item in items:
        label = bill_label(item["bill_type"], item["bill_number"]) if item["bill_type"] else item["measure_number"]
        item["measure_label"] = f"{label} to {item['amends']}" if item["amends"] else label
    latest = senate_sessions[-1] if senate_sessions else {}
    return {
        "items": items,
        # Set when the Senate adjourns; null while it's in session or before any data.
        "senate_next_convene_et": latest.get("next_convene_time_et"),
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
