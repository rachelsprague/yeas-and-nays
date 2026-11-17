"""Parse Congress.gov responses: bills (details), CRS summaries (one per bill version), and
the bills each member sponsored and cosponsored."""

import json
from pathlib import Path


def parse_summaries(content: bytes, source_file: str) -> list[dict]:
    doc = json.loads(content)
    request = doc["request"]
    return [
        {
            "source_file": source_file,
            "congress": request["congress"],
            "bill_type": request["billType"],
            "bill_number": request["billNumber"],
            "version_code": s.get("versionCode"),
            "action_date": s.get("actionDate"),
            "action_desc": s.get("actionDesc"),
            "update_date": s.get("updateDate"),
            "summary_html": s.get("text"),
        }
        for s in doc["summaries"]
    ]


def parse_bill(content: bytes, source_file: str) -> dict:
    bill = json.loads(content)["bill"]
    # A bill has one sponsor; the API returns a list. (Committee-reported
    # measures can have none.)
    sponsor = (bill.get("sponsors") or [{}])[0]
    return {
        "source_file": source_file,
        "congress": str(bill["congress"]),
        "bill_type": bill["type"].lower(),
        "bill_number": str(bill["number"]),
        "title": bill.get("title"),
        "introduced_date": bill.get("introducedDate"),
        "origin_chamber": bill.get("originChamber"),
        "sponsor_bioguide_id": sponsor.get("bioguideId"),
        "sponsor_full_name": sponsor.get("fullName"),
        "cosponsor_count": str((bill.get("cosponsors") or {}).get("count", 0)),
        "policy_area": (bill.get("policyArea") or {}).get("name"),
        "legislation_url": bill.get("legislationUrl"),
        "update_date": bill.get("updateDate"),
    }


def parse_sponsored(content: bytes, source_file: str) -> list[dict]:
    return parse_member_list(content, source_file, "sponsoredLegislation")


def parse_cosponsored(content: bytes, source_file: str) -> list[dict]:
    return parse_member_list(content, source_file, "cosponsoredLegislation")


def parse_member_list(content: bytes, source_file: str, list_key: str) -> list[dict]:
    return member_list_rows(json.loads(content), source_file, list_key)


def member_list_rows(doc: dict, source_file: str, list_key: str) -> list[dict]:
    """One row per bill in a member's list. The fetch drops repeats, but a file cached
    before it did can still hold one, so repeats (same Congress, type and number) are
    dropped here too, keeping the first."""
    seen = set()
    items = []
    for item in doc[list_key]:
        bill = (str(item["congress"]), item["type"].lower(), str(item["number"]))
        if bill not in seen:
            seen.add(bill)
            items.append(item)
    return [
        {
            "source_file": source_file,
            "bioguide_id": doc["bioguideId"],
            "congress": str(item["congress"]),
            "bill_type": item["type"].lower(),
            "bill_number": str(item["number"]),
            "title": item.get("latestTitle") or item.get("title"),
            "introduced_date": item.get("introducedDate"),
            "latest_action_date": (item.get("latestAction") or {}).get("actionDate"),
            "latest_action_text": (item.get("latestAction") or {}).get("text"),
            "policy_area": (item.get("policyArea") or {}).get("name"),
        }
        for item in items
    ]


def parse_sponsored_dir(raw_root: Path) -> tuple[list[dict], list[dict]]:
    """(sponsored, lists): every sponsored bill, and one row per member whose list has been
    fetched (see parse_member_lists_dir)."""
    return parse_member_lists_dir(raw_root, "sponsored")


def parse_cosponsored_dir(raw_root: Path) -> tuple[list[dict], list[dict]]:
    """(cosponsored, lists): every cosponsored bill, and one row per member whose list has
    been fetched (see parse_member_lists_dir)."""
    return parse_member_lists_dir(raw_root, "cosponsored")


def parse_member_lists_dir(raw_root: Path, kind: str) -> tuple[list[dict], list[dict]]:
    """(bills, lists) for one kind of member list. Lists fill in over several runs, and a
    fetch that fails leaves no file, so a member with no rows may just not have been fetched
    yet; `lists` tells that apart from a list with nothing on it."""
    bills, lists = [], []
    for path in sorted(raw_root.glob(f"*/{kind}/*.json")):
        source_file = str(path.relative_to(raw_root))
        doc = json.loads(path.read_bytes())
        rows = member_list_rows(doc, source_file, f"{kind}Legislation")
        bills += rows
        lists.append({"source_file": source_file, "bioguide_id": doc["bioguideId"],
                      "congress": str(doc["congress"]), "bill_count": str(len(rows))})
    return bills, lists


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict]]:
    """(bills, summaries) from everything under data/raw/congress_gov/."""
    bills = [parse_bill(p.read_bytes(), str(p.relative_to(raw_root)))
             for p in sorted(raw_root.glob("*/bills/*.json"))]
    summaries = []
    for path in sorted(raw_root.glob("*/summaries/*.json")):
        summaries += parse_summaries(path.read_bytes(), str(path.relative_to(raw_root)))
    return bills, summaries
