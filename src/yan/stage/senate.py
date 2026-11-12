"""Parse Senate roll call XML into vote and position rows."""

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
    vote = {
        "source_file": source_file,
        "congress": _text(root, "congress"),
        "session": _text(root, "session"),
        "vote_number": _text(root, "vote_number"),
        "vote_date": _text(root, "vote_date"),
        "modify_date": _text(root, "modify_date"),
        "vote_question_text": _text(root, "vote_question_text"),
        "vote_document_text": _text(root, "vote_document_text"),
        "vote_result_text": _text(root, "vote_result_text"),
        "question": _text(root, "question"),
        "vote_title": _text(root, "vote_title"),
        "majority_requirement": _text(root, "majority_requirement"),
        "vote_result": _text(root, "vote_result"),
        "document_type": _text(root, "document/document_type"),
        "document_number": _text(root, "document/document_number"),
        "document_name": _text(root, "document/document_name"),
        "document_title": _text(root, "document/document_title"),
        "document_short_title": _text(root, "document/document_short_title"),
        "amendment_number": _text(root, "amendment/amendment_number"),
        "amendment_purpose": _text(root, "amendment/amendment_purpose"),
        "yeas": _text(root, "count/yeas"),
        "nays": _text(root, "count/nays"),
        "present": _text(root, "count/present"),
        "absent": _text(root, "count/absent"),
        "tie_breaker_by_whom": _text(root, "tie_breaker/by_whom"),
        "tie_breaker_vote": _text(root, "tie_breaker/tie_breaker_vote"),
    }

    positions = []
    for m in root.iterfind("members/member"):
        positions.append({
            "source_file": source_file,
            "congress": vote["congress"],
            "session": vote["session"],
            "vote_number": vote["vote_number"],
            "lis_member_id": _text(m, "lis_member_id"),
            "member_full": _text(m, "member_full"),
            "first_name": _text(m, "first_name"),
            "last_name": _text(m, "last_name"),
            "party": _text(m, "party"),
            "state": _text(m, "state"),
            "vote_cast": _text(m, "vote_cast"),
        })
    return vote, positions


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict]]:
    votes, positions = [], []
    for path in sorted(raw_root.glob("*/*/vote_[0-9]*.xml")):
        vote, pos = parse_vote(path.read_bytes(), path.relative_to(raw_root).as_posix())
        votes.append(vote)
        positions.extend(pos)
    return votes, positions
