"""Parse House Clerk roll call XML into vote and position rows."""

from pathlib import Path

import defusedxml.ElementTree as ET


def _text(el, path: str) -> str | None:
    value = el.findtext(path)
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def parse_vote(content: bytes, source_file: str) -> tuple[dict, list[dict]]:
    root = ET.fromstring(content)
    meta = root.find("vote-metadata")
    time_el = meta.find("action-time")
    totals = meta.find("vote-totals/totals-by-vote")

    vote = {
        "source_file": source_file,
        "congress": _text(meta, "congress"),
        "session": _text(meta, "session"),
        "rollcall_num": _text(meta, "rollcall-num"),
        "legis_num": _text(meta, "legis-num"),
        "vote_question": _text(meta, "vote-question"),
        "vote_type": _text(meta, "vote-type"),
        "vote_result": _text(meta, "vote-result"),
        "action_date": _text(meta, "action-date"),
        "action_time_etz": time_el.get("time-etz") if time_el is not None else None,
        "vote_desc": _text(meta, "vote-desc"),
        "amendment_num": _text(meta, "amendment-num"),
        "amendment_author": _text(meta, "amendment-author"),
        # Absent on votes tallied by candidate (Election of the Speaker).
        "yea_total": _text(totals, "yea-total") if totals is not None else None,
        "nay_total": _text(totals, "nay-total") if totals is not None else None,
        "present_total": _text(totals, "present-total") if totals is not None else None,
        "not_voting_total": _text(totals, "not-voting-total") if totals is not None else None,
    }

    positions = []
    for rv in root.iterfind("vote-data/recorded-vote"):
        leg = rv.find("legislator")
        positions.append({
            "source_file": source_file,
            "congress": vote["congress"],
            "session": vote["session"],
            "rollcall_num": vote["rollcall_num"],
            "bioguide_id": leg.get("name-id"),
            "name": _text(rv, "legislator"),
            "party": leg.get("party"),
            "state": leg.get("state"),
            "vote": _text(rv, "vote"),
        })
    return vote, positions


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict]]:
    votes, positions = [], []
    for path in sorted(raw_root.glob("*/roll*.xml")):
        vote, pos = parse_vote(path.read_bytes(), path.relative_to(raw_root).as_posix())
        votes.append(vote)
        positions.extend(pos)
    return votes, positions
