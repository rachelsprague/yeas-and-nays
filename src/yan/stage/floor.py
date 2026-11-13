"""Parse the House and Senate floor schedule files into rows.

House weekly schedule: one row per floor item (subitems, such as the committee
reports that accompany a bill, are left out). Removed items are kept with
their remove date; dbt drops them.

Senate daily floor activity: one row per status line on each bill, amendment
or nomination ("Cloture motion presented in Senate."), in the order recorded.
Senate session days: one row per time the Senate convened.
"""

import re
from pathlib import Path

import defusedxml.ElementTree as ET


def _text(el, path: str) -> str | None:
    value = el.findtext(path)
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def parse_house_week(content: bytes, source_file: str) -> list[dict]:
    root = ET.fromstring(content)
    rows = []
    for category in root.iterfind("category"):
        for item in category.iterfind("floor-items/floor-item"):
            rows.append({
                "source_file": source_file,
                "congress": root.get("congress-num"),
                "week_date": root.get("week-date"),
                "category": " ".join(category.get("type", "").split()) or None,
                "category_order": category.get("sort-order"),
                "item_id": item.get("id"),
                "item_order": item.get("sort-order"),
                "legis_num": _text(item, "legis-num"),
                "floor_text": _text(item, "floor-text"),
                "add_date": item.get("add-date") or None,
                "remove_date": item.get("remove-date") or None,
            })
    return rows


def parse_senate_day(content: bytes, source_file: str) -> list[dict]:
    root = ET.fromstring(content)
    activity_date = _text(root, "date_iso_8601")
    rows = []
    # Amendments are <document> elements nested under the measure they amend.
    for document in root.iter("document"):
        statuses = [
            " ".join((s.text or "").split())
            for s in document
            if s.tag in ("document_status_text", "amendment_status_text")
        ]
        for order, status in enumerate(s for s in statuses if s):
            rows.append({
                "source_file": source_file,
                "activity_date": activity_date,
                "docnum": _text(document, "docnum"),
                "document_prefix": _text(document, "document_prefix"),
                "document_num": _text(document, "document_num"),
                "amends": _text(document, "amendment_docnum"),
                "sponsor_name": _text(document, "sponsor_name"),
                # Titles wrap mid-sentence in the source, leaving "contact\n." -> "contact .".
                "document_title": re.sub(r" ([.,;:])", r"\1", _text(document, "document_title") or "") or None,
                "status_order": str(order),
                "status_text": status,
            })
    return rows


def parse_session_days(content: bytes, source_file: str) -> list[dict]:
    root = ET.fromstring(content)
    return [
        {
            "source_file": source_file,
            "legislative_day": (day.get("LegislativeDayDate") or "")[:10] or None,
            "convene_time": _text(session, "ConveneDate"),
            "adjourn_time": _text(session, "AdjournDate"),
            "next_convene_time": _text(session, "NextConveneDate"),
        }
        for day in root.iter("LegislativeDay")
        for session in day.iterfind("SessionDay")
    ]


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    house, senate, days = [], [], []
    for path in sorted(raw_root.glob("house/????-??-??.xml")):
        house.extend(parse_house_week(path.read_bytes(), path.relative_to(raw_root).as_posix()))
    for path in sorted(raw_root.glob("senate/????-??-??.xml")):
        senate.extend(parse_senate_day(path.read_bytes(), path.relative_to(raw_root).as_posix()))
    days_file = raw_root / "senate" / "session_days.xml"
    if days_file.exists():
        days = parse_session_days(days_file.read_bytes(), days_file.relative_to(raw_root).as_posix())
    return house, senate, days
