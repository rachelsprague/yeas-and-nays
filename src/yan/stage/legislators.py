"""Flatten congress-legislators JSON into people, terms, party affiliations,
and official social media accounts.

A term can carry `party_affiliations` when a member changes party mid-term;
those periods are emitted as their own rows so dbt can resolve party and
caucus as of each vote's date.

An entry whose bioguide ID isn't a capital letter and six digits is logged
and skipped: the ID goes into Congress.gov request URLs, cache file names
and page URLs.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

SOURCES = {"legislators-current.json": True, "legislators-historical.json": False}
SOCIAL_FILE = "legislators-social-media.json"
SOCIAL_FIELDS = ["twitter", "facebook", "instagram", "youtube", "youtube_id", "mastodon"]
BIOGUIDE_ID = re.compile(r"[A-Z][0-9]{6}")


def parse(people: list[dict], is_current: bool) -> tuple[list[dict], list[dict], list[dict]]:
    person_rows, term_rows, affiliation_rows = [], [], []
    for p in people:
        bioguide = _bioguide(p["id"])
        if not bioguide:
            continue
        name = p.get("name", {})
        person_rows.append({
            "bioguide_id": bioguide,
            "lis_id": p["id"].get("lis"),
            "first_name": name.get("first"),
            "last_name": name.get("last"),
            "official_full_name": name.get("official_full"),
            "is_current": is_current,
        })
        for t in p.get("terms", []):
            term_rows.append({
                "bioguide_id": bioguide,
                "term_type": t.get("type"),
                "term_start": t.get("start"),
                "term_end": t.get("end"),
                "state": t.get("state"),
                "district": t.get("district"),
                "party": t.get("party"),
                "caucus": t.get("caucus"),
                "url": t.get("url"),
                "contact_form": t.get("contact_form"),
                "phone": t.get("phone"),
                "office": t.get("office"),
            })
            for a in t.get("party_affiliations", []):
                affiliation_rows.append({
                    "bioguide_id": bioguide,
                    "term_start": t.get("start"),
                    "affiliation_start": a.get("start"),
                    "affiliation_end": a.get("end"),
                    "party": a.get("party"),
                    "caucus": a.get("caucus"),
                })
    return person_rows, term_rows, affiliation_rows


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    people, terms, affiliations = [], [], []
    for filename, is_current in SOURCES.items():
        data = json.loads((raw_root / filename).read_text())
        p, t, a = parse(data, is_current)
        people += p
        terms += t
        affiliations += a
    return people, terms, affiliations


def parse_social(entries: list[dict]) -> list[dict]:
    """One row per member with the account names (handles) as recorded."""
    rows = []
    for e in entries:
        bioguide = _bioguide(e.get("id", {}))
        if not bioguide:
            continue
        social = e.get("social", {})
        rows.append({"bioguide_id": bioguide} | {f: _text(social.get(f)) for f in SOCIAL_FIELDS})
    return rows


def parse_social_dir(raw_root: Path) -> list[dict]:
    # Accounts are secondary: a raw folder from before this file was ingested
    # stages no accounts rather than failing the run.
    path = raw_root / SOCIAL_FILE
    if not path.exists():
        log.warning("legislators: %s not found; no social media accounts staged", SOCIAL_FILE)
        return []
    return parse_social(json.loads(path.read_text()))


def _bioguide(ids: dict) -> str | None:
    """The entry's bioguide ID, or None when it has none or it's malformed (logged)."""
    value = ids.get("bioguide")
    if not value:
        return None
    if isinstance(value, str) and BIOGUIDE_ID.fullmatch(value):
        return value
    log.warning("legislators: skipping an entry with malformed bioguide ID %r", value)
    return None


def _text(value) -> str | None:
    return None if value is None else str(value)
