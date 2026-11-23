"""Flatten congress-legislators JSON into people, terms, party affiliations,
and official social media accounts.

A term can carry `party_affiliations` when a member changes party mid-term;
those periods are emitted as their own rows so dbt can resolve party and
caucus as of each vote's date.

An entry whose bioguide ID isn't a capital letter and six digits is logged
and skipped: the ID goes into Congress.gov request URLs, cache file names
and page URLs. An entry with no ID block, or no bioguide ID, is logged and
skipped too, as is a list item that isn't an object (an entry, term or
party affiliation). A null or non-object name or social block reads as
empty, and null or non-list terms or affiliations as none. A field value of
the wrong type (an object or list where text is expected, or a district that
isn't a whole number) is logged and staged as null; a House term left with
no district fails the dbt test `house_terms_have_a_district`. A file whose
top level isn't a list fails the run: read key by key, it would stage no
one. If the member has votes in the data, a skipped entry shows up
downstream as a dbt test failure (its vote positions fail the positions
mart's relationships or not_null test on bioguide_id), so check this log
when one appears; otherwise the log is the only trace.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

SOURCES = {"legislators-current.json": True, "legislators-historical.json": False}
SOCIAL_FILE = "legislators-social-media.json"
SOCIAL_FIELDS = ["twitter", "facebook", "instagram", "youtube", "youtube_id", "mastodon", "bluesky"]
BIOGUIDE_ID = re.compile(r"[A-Z][0-9]{6}")
LABEL_MAX = 80


def parse(people: list[dict], is_current: bool) -> tuple[list[dict], list[dict], list[dict]]:
    person_rows, term_rows, affiliation_rows = [], [], []
    for p in people:
        if not _is_entry(p):
            continue
        ids = p.get("id")
        name = _object(p.get("name"))
        bioguide = _bioguide(ids, name.get("official_full") or name.get("last"))
        if not bioguide:
            continue

        def text(entry: dict, field: str) -> str | None:
            return _text(entry.get(field), field, bioguide)

        person_rows.append({
            "bioguide_id": bioguide,
            "lis_id": text(ids, "lis"),
            "first_name": text(name, "first"),
            "last_name": text(name, "last"),
            "official_full_name": text(name, "official_full"),
            "is_current": is_current,
        })
        for t in _list(p.get("terms")):
            if not _is_entry(t):
                continue
            term_start = text(t, "start")
            term_rows.append({
                "bioguide_id": bioguide,
                "term_type": text(t, "type"),
                "term_start": term_start,
                "term_end": text(t, "end"),
                "state": text(t, "state"),
                "district": _int(t.get("district"), "district", bioguide),
                "party": text(t, "party"),
                "caucus": text(t, "caucus"),
                "url": text(t, "url"),
                "contact_form": text(t, "contact_form"),
                "phone": text(t, "phone"),
                "office": text(t, "office"),
            })
            for a in _list(t.get("party_affiliations")):
                if not _is_entry(a):
                    continue
                affiliation_rows.append({
                    "bioguide_id": bioguide,
                    "term_start": term_start,
                    "affiliation_start": text(a, "start"),
                    "affiliation_end": text(a, "end"),
                    "party": text(a, "party"),
                    "caucus": text(a, "caucus"),
                })
    return person_rows, term_rows, affiliation_rows


def parse_dir(raw_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    people, terms, affiliations = [], [], []
    for filename, is_current in SOURCES.items():
        p, t, a = parse(_load(raw_root / filename), is_current)
        people += p
        terms += t
        affiliations += a
    return people, terms, affiliations


def parse_social(entries: list[dict]) -> list[dict]:
    """One row per member with the account names (handles) as recorded."""
    rows = []
    for e in entries:
        if not _is_entry(e):
            continue
        bioguide = _bioguide(e.get("id"), e.get("id"))
        if not bioguide:
            continue
        social = _object(e.get("social"))
        rows.append({"bioguide_id": bioguide} | {f: _text(social.get(f), f, bioguide) for f in SOCIAL_FIELDS})
    return rows


def parse_social_dir(raw_root: Path) -> list[dict]:
    # Accounts are secondary: a raw folder from before this file was ingested
    # stages no accounts rather than failing the run.
    path = raw_root / SOCIAL_FILE
    if not path.exists():
        log.warning("legislators: %s not found; no social media accounts staged", SOCIAL_FILE)
        return []
    return parse_social(_load(path))


def _load(path: Path) -> list:
    """A file's entries; raises when its top level isn't a list."""
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"legislators: {path.name} top level is {type(data).__name__}, not a list")
    return data


def _is_entry(entry) -> bool:
    """Whether a list item is an object to read; anything else is logged."""
    if isinstance(entry, dict):
        return True
    log.warning("legislators: skipping a list item that isn't an object (%s)", _label(entry))
    return False


def _bioguide(ids, label) -> str | None:
    """The entry's bioguide ID, or None when it has none or it's malformed (logged).

    `label` names the entry in the log.
    """
    value = ids.get("bioguide") if isinstance(ids, dict) else None
    if not value:
        log.warning("legislators: skipping an entry with no bioguide ID (%s)", _label(label))
        return None
    if isinstance(value, str) and BIOGUIDE_ID.fullmatch(value):
        return value
    log.warning("legislators: skipping an entry with malformed bioguide ID %s (%s)",
                _label(value), _label(label))
    return None


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _label(value) -> str:
    """repr() for the log, cut to LABEL_MAX characters."""
    text = repr(value)
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1] + "…"


def _text(value, field: str, bioguide: str) -> str | None:
    """A text field as text (numbers too); an object, list or boolean is logged and read as null."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    _wrong_type(value, field, bioguide)
    return None


def _int(value, field: str, bioguide: str) -> int | None:
    """A whole-number field; any other value is logged and read as null."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    _wrong_type(value, field, bioguide)
    return None


def _wrong_type(value, field: str, bioguide: str) -> None:
    log.warning("legislators: %s has a %s of the wrong type, staged as null (%s)",
                bioguide, field, _label(value))
