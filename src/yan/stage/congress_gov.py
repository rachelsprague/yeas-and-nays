"""Parse Congress.gov responses: bills (details), CRS summaries (one per bill version), and
the bills each member sponsored."""

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
    doc = json.loads(content)
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
        for item in doc["sponsoredLegislation"]
    ]


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """(bills, summaries, sponsored) from everything under data/raw/congress_gov/."""
    bills = [parse_bill(p.read_bytes(), str(p.relative_to(raw_root)))
             for p in sorted(raw_root.glob("*/bills/*.json"))]
    summaries = []
    for path in sorted(raw_root.glob("*/summaries/*.json")):
        summaries += parse_summaries(path.read_bytes(), str(path.relative_to(raw_root)))
    sponsored = []
    for path in sorted(raw_root.glob("*/sponsored/*.json")):
        sponsored += parse_sponsored(path.read_bytes(), str(path.relative_to(raw_root)))
    return bills, summaries, sponsored
