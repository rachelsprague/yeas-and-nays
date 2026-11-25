"""Export the dbt marts to small, deterministic JSON files under data/out/.

    data/out/meta.json            congress, counts, latest roll number per chamber/session
    data/out/members.json         one entry per member, with their stats this Congress
    data/out/members/{bioguide}.json  one member: bills and resolutions they introduced
                                  and cosponsored this Congress, newest first
                                  (each list is null until first fetched), and their
                                  Congressional Directory biography (null if none)
    data/out/floor_schedule.json  what may come up for a vote: the House's weekly
                                  floor schedule and pending Senate cloture motions,
                                  plus when the Senate next convenes and each
                                  chamber's floor status (in session or next convening)
    data/out/votes.json           one entry per vote (metadata + tallies, and whether
                                  the bot posts it), newest first
    data/out/votes/{vote_id}.json one vote: metadata, party totals, caucus majorities,
                                  members who voted against their party majority,
                                  every member's position as recorded, the CRS
                                  summary of the measure, when there is one, and the
                                  measure's path from introduction to law

Output is a pure function of the warehouse: keys are sorted, each list
element sits on its own line, and nothing time-of-run is written. A re-run
with no new data produces no git diff.

A past Congress's votes never leave the site: if a vote from before the
current Congress is in the existing votes.json but not the warehouse (its raw
files lost), export fails before writing anything, so the run commits nothing
and the vote's page stays up.
"""

import datetime as dt
import json
import logging
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from yan.bot.rules import decide, measure_label
from yan.config import CONGRESS, OUT_DIR, WAREHOUSE_PATH
from yan.export import summary_html
from yan.export.bill_path import vote_path
from yan.measures import bill_label

log = logging.getLogger(__name__)

VOTE_ORDER = "vote_time_et desc, chamber, roll_number desc"
EASTERN = ZoneInfo("America/New_York")


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


def check_past_votes_kept(out_dir: Path, votes: list[dict]) -> None:
    """Raise if a past Congress's vote in the existing votes.json is missing from `votes`."""
    path = out_dir / "votes.json"
    if not path.exists():
        return
    kept = {v["vote_id"] for v in votes}
    lost = sorted(v["vote_id"] for v in json.loads(path.read_text())["votes"]
                  if int(v["congress"]) < CONGRESS and v["vote_id"] not in kept)
    if lost:
        raise RuntimeError(f"export: {len(lost)} votes from past Congresses are missing from the "
                           f"warehouse (e.g. {lost[0]}); their raw files may be lost. Nothing written.")


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
        # A member's top-level stats are for their last Congress; `congresses` has each one.
        members = _rows(con, """
            select members.*,
                   stats.* exclude (bioguide_id, congress, served_in_congress, served_from, served_to)
            from members
            left join member_congresses as stats
                on stats.bioguide_id = members.bioguide_id and stats.congress = members.last_congress
            order by bioguide_id
        """)
        member_congresses = _rows(con, "select * from member_congresses order by bioguide_id, congress desc")
        votes = [with_bot_posts(with_measure_label(v)) for v in _rows(con, f"select * from votes order by {VOTE_ORDER}")]
        positions = _rows(con, """
            select vote_id, bioguide_id, member_label, chamber, state, district, party, caucus_party, position_raw,
                   position, caucus_majority_position, voted_against_party_majority
            from positions
            order by vote_id, member_label, bioguide_id
        """)
        sponsored = _rows(con, """
            select bioguide_id, cast(congress as integer) as congress, bill_id, bill_type, bill_number,
                   title, introduced_date, latest_action_date, latest_action_text, policy_area,
                   congress_gov_url, latest_vote_id
            from sponsored_bills
            order by bioguide_id, introduced_date desc, bill_type, try_cast(bill_number as integer) desc
        """)
        cosponsored = _rows(con, """
            select bioguide_id, cast(congress as integer) as congress, bill_id, bill_type, bill_number,
                   title, introduced_date, latest_action_date, latest_action_text, policy_area,
                   congress_gov_url, latest_vote_id
            from cosponsored_bills
            order by bioguide_id, introduced_date desc, bill_type, try_cast(bill_number as integer) desc
        """)
        bios = {
            row.pop("bioguide_id"): row
            for row in _rows(con, """
                select bioguide_id, edition, date_issued, opening, education, professional_history,
                       military_service
                from member_bios
            """)
        }
        sponsored_fetched = _fetched_lists(con, "sponsored_lists")
        cosponsored_fetched = _fetched_lists(con, "cosponsored_lists")
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
            select convene_time_et, adjourn_time_et, next_convene_time_et, next_convene_pro_forma
            from senate_sessions
            order by convene_time_et
        """)
        house_days = _rows(con, """
            select convene_time_et, adjourned, next_convene_time_et
            from house_floor_days
            order by legislative_day
        """)
        milestones = defaultdict(dict)
        for row in _rows(con, """
            select congress, bill_type, bill_number, milestone, first_date, last_date
            from bill_milestones
        """):
            bill = (row["congress"], row["bill_type"], row["bill_number"])
            milestones[bill][row["milestone"]] = (row["first_date"], row["last_date"])
        summaries = {
            row.pop("vote_id"): row
            for row in _rows(con, """
                select vote_id, version_code, action_date, action_desc, summary_html
                from vote_summaries
            """)
        }
    finally:
        con.close()

    check_past_votes_kept(out_dir, votes)

    by_vote = defaultdict(list)
    for p in positions:
        by_vote[p["vote_id"]].append(p)

    congresses_by = defaultdict(list)
    for row in member_congresses:
        congresses_by[row.pop("bioguide_id")].append(row)
    for member in members:
        member["congresses"] = congresses_by[member["bioguide_id"]]

    members_by_id = {m["bioguide_id"]: m for m in members}

    changed = 0
    changed += write_if_changed(out_dir / "members.json", dumps({"congress": CONGRESS, "members": members}))
    changed += write_if_changed(out_dir / "votes.json", dumps({"congress": CONGRESS, "votes": votes}))

    vote_dir = out_dir / "votes"
    expected = set()
    for vote in votes:
        name = f"{vote['vote_id']}.json"
        expected.add(name)
        bill = (vote["congress"], vote["bill_type"], vote["bill_number"])
        doc = vote_document(vote, by_vote[vote["vote_id"]], members_by_id, summaries.get(vote["vote_id"]),
                            vote_path(vote, milestones.get(bill, {})))
        changed += write_if_changed(vote_dir / name, dumps(doc))

    # Remove files for votes no longer in the warehouse.
    for path in vote_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
            changed += 1

    sponsored_by, cosponsored_by = defaultdict(list), defaultdict(list)
    for bills, by_list in ((sponsored, sponsored_by), (cosponsored, cosponsored_by)):
        for bill in bills:
            bill["measure_label"] = bill_label(bill["bill_type"], bill["bill_number"])
            by_list[(bill.pop("bioguide_id"), bill.pop("congress"))].append(bill)
    member_dir = out_dir / "members"
    expected = set()
    for member in members:
        name = f"{member['bioguide_id']}.json"
        expected.add(name)
        bioguide_id = member["bioguide_id"]
        doc = {
            "bioguide_id": bioguide_id,
            # One list per Congress, newest first, for each Congress whose list has been
            # fetched. Null until any is (a fetch can fail, and cosponsored lists fill in over
            # several runs), so the site can leave the section out rather than show none.
            "sponsored": member_lists(bioguide_id, sponsored_fetched, sponsored_by),
            "cosponsored": member_lists(bioguide_id, cosponsored_fetched, cosponsored_by),
            # From the newest Congressional Directory, as printed; null when it has none.
            "bio": bios.get(bioguide_id),
        }
        changed += write_if_changed(member_dir / name, dumps(doc))
    for path in member_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
            changed += 1

    changed += write_if_changed(
        out_dir / "floor_schedule.json", dumps(floor_schedule_document(floor_items, senate_sessions, house_days))
    )

    meta = meta_document(votes, members)
    # False when no Congress.gov sponsored list has been fetched (e.g. no API key), so the
    # site can hide the section instead of showing every member with no bills.
    meta["has_sponsored_bills"] = bool(sponsored_fetched)
    changed += write_if_changed(out_dir / "meta.json", dumps(meta))
    log.info("export: %d votes, %d members, %d files changed", len(votes), len(members), changed)


def _fetched_lists(con, table: str) -> dict[str, list[int]]:
    """Bioguide ID -> the Congresses whose list of this kind has been fetched, newest first."""
    fetched = defaultdict(list)
    for row in _rows(con, f"select bioguide_id, congress from {table} order by congress desc"):
        fetched[row["bioguide_id"]].append(row["congress"])
    return fetched


def member_lists(bioguide_id: str, fetched: dict[str, list[int]], bills: dict) -> list[dict] | None:
    """A member's sponsored or cosponsored bills as one group per fetched Congress, newest
    first ({"congress": 120, "bills": [...]}), or None when no list has been fetched."""
    if bioguide_id not in fetched:
        return None
    return [{"congress": c, "bills": bills.get((bioguide_id, c), [])} for c in fetched[bioguide_id]]


def with_measure_label(vote: dict) -> dict:
    """Add the measure number in citation form ("H RES 1655" -> "H.Res. 1655") for display."""
    return {**vote, "measure_label": measure_label(vote)}


def with_bot_posts(vote: dict) -> dict:
    """Add whether the bot posts the vote (yan.bot.rules), so the site can list the same votes."""
    return {**vote, "bot_posts": decide(vote).post}


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


SEAT_FIELDS = ("chamber", "state", "district", "party", "caucus_party")


def members_as_of_vote(positions: list[dict], members: dict[str, dict]) -> dict[str, dict]:
    """Party, caucus and seat on the vote date, for the members whose latest (in members.json) differ."""
    as_of = {}
    for p in positions:
        seat = {field: p[field] for field in SEAT_FIELDS}
        latest = members[p["bioguide_id"]]
        if seat != {field: latest[field] for field in SEAT_FIELDS}:
            as_of[p["bioguide_id"]] = seat
    return as_of


def vote_document(vote: dict, positions: list[dict], members: dict[str, dict], summary: dict | None = None,
                  path: dict | None = None) -> dict:
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
        "members_as_of_vote": members_as_of_vote(positions, members),
        "positions": {p["bioguide_id"]: p["position_raw"] for p in positions},
        "summary": summary_document(summary),
        "path": path,
    }


def floor_schedule_document(items: list[dict], senate_sessions: list[dict], house_days: list[dict]) -> dict:
    """Floor schedule items with a display label, when the Senate is next set to convene,
    and each chamber's floor status.

    The label is the citation form for bills and resolutions ("H.Res. 1650"), else
    the number as listed ("PN1272-3", "H. Res. ___"); amendments name what they amend
    ("Amendment to H.R. 2347" when the amendment's own number is missing).
    """
    for item in items:
        label = bill_label(item["bill_type"], item["bill_number"]) if item["bill_type"] else item["measure_number"]
        item["measure_label"] = f"{label or 'Amendment'} to {item['amends']}" if item["amends"] else label or None
    latest = senate_sessions[-1] if senate_sessions else {}
    # senate.gov flags a pro forma session on the session before it, so one
    # under way (no adjournment yet) is pro forma if the previous row says so.
    previous = senate_sessions[-2] if len(senate_sessions) > 1 else {}
    senate_open = latest and not latest.get("adjourn_time_et") and previous.get("next_convene_pro_forma") is not True
    house = house_days[-1] if house_days else {}
    return {
        "items": items,
        # Set when the Senate adjourns; null while it's in session or before any data.
        "senate_next_convene_et": latest.get("next_convene_time_et"),
        "floor_status": {
            "senate": floor_status(
                convened=latest.get("convene_time_et") if senate_open else None,
                next_convene=latest.get("next_convene_time_et"),
                pro_forma=latest.get("next_convene_pro_forma"),
            ),
            "house": floor_status(
                convened=house.get("convene_time_et") if house and not house.get("adjourned") else None,
                next_convene=house.get("next_convene_time_et") if house.get("adjourned") else None,
                pro_forma=None,  # The Clerk's file doesn't say.
            ),
        },
    }


def floor_status(convened: dt.datetime | None, next_convene: dt.datetime | None, pro_forma: bool | None) -> dict:
    """A chamber's floor status as of the latest data: when it convened if it hadn't
    adjourned yet, else when it next convenes and whether that's a pro forma session
    (null when not recorded). Times carry their Eastern offset, so a browser can
    compare them with its own clock."""
    return {
        "convened_at": _eastern(convened),
        "next_convene_at": _eastern(next_convene),
        "next_convene_pro_forma": pro_forma,
    }


def _eastern(value: dt.datetime | None) -> dt.datetime | None:
    return value.replace(tzinfo=EASTERN) if value else None


def meta_document(votes: list[dict], members: list[dict]) -> dict:
    # Chamber -> Congress -> session -> latest roll number (roll numbers restart each session).
    latest = defaultdict(lambda: defaultdict(dict))
    for v in votes:
        by_session = latest[v["chamber"]][str(v["congress"])]
        key = str(v["session"])
        by_session[key] = max(by_session.get(key, 0), v["roll_number"])
    return {
        "congress": CONGRESS,
        "vote_count": len(votes),
        "member_count": len(members),
        "latest_vote_date": max((v["vote_date"] for v in votes), default=None),
        "latest_roll_number": latest,
    }
