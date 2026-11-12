"""Parse Congress.gov bill summary responses into one row per summary (per bill version)."""

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


def parse_dir(raw_root: Path) -> list[dict]:
    rows = []
    for path in sorted(raw_root.glob("*/summaries/*.json")):
        rows += parse_summaries(path.read_bytes(), str(path.relative_to(raw_root)))
    return rows
