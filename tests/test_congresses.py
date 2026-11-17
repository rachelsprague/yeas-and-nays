"""Tracking more than one Congress: a past Congress's raw files are fetched only when
missing (once it's been over REFRESH_AFTER_END since it ended), bills are fetched under
their own vote's Congress, and export never drops a past Congress's votes."""

import datetime as dt
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

from yan.http import Client

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE_VOTE = (FIXTURES / "house_2025_roll010.xml").read_bytes()  # <congress>119</congress>
NOT_A_VOTE = b"<error>File not found</error>"
# The 119th Congress ends 2027-01-03; it's refreshed until 60 days after.
JUST_ENDED = dt.date(2027, 1, 20)
LONG_ENDED = dt.date(2027, 6, 1)


def test_recently_ended():
    from yan.config import recently_ended

    sessions = {1: 2025, 2: 2026}
    assert recently_ended(sessions, dt.date(2026, 11, 16))  # still in session
    assert recently_ended(sessions, JUST_ENDED)
    assert recently_ended(sessions, dt.date(2027, 3, 3))  # 59 days after Jan. 3
    assert not recently_ended(sessions, dt.date(2027, 3, 4))
    assert not recently_ended(sessions, LONG_ENDED)


def _client(handler, fetched):
    def record(request):
        fetched.append(str(request.url))
        return handler(request)

    return Client(delay=0, transport=httpx.MockTransport(record))


def _house_setup(monkeypatch, tmp_path, current, last_roll):
    from yan.ingest import house

    monkeypatch.setattr(house, "RAW_DIR", tmp_path)
    monkeypatch.setattr(house, "CONGRESS", current)
    (tmp_path / "house" / "2025").mkdir(parents=True)
    for roll in range(1, 31):
        (tmp_path / "house" / "2025" / f"roll{roll:03d}.xml").write_bytes(HOUSE_VOTE)

    def handler(request):
        roll = int(request.url.path.rsplit("roll", 1)[1].removesuffix(".xml"))
        return httpx.Response(200, content=HOUSE_VOTE if roll <= last_roll else NOT_A_VOTE)

    return house, handler


def test_house_past_congress_walks_on_from_its_last_file(monkeypatch, tmp_path):
    house, handler = _house_setup(monkeypatch, tmp_path, current=120, last_roll=31)
    fetched = []
    house.ingest(_client(handler, fetched), {119: {1: 2025}}, LONG_ENDED)
    # No refresh of recent votes: roll 31 is new, then two misses end the walk.
    assert fetched == [house.URL.format(year=2025, roll=r) for r in (31, 32, 33)]
    assert (tmp_path / "house" / "2025" / "roll031.xml").exists()


@pytest.mark.parametrize("current, today", [(119, LONG_ENDED), (120, JUST_ENDED)])
def test_house_current_or_just_ended_congress_refreshes_its_recent_votes(monkeypatch, tmp_path, current, today):
    house, handler = _house_setup(monkeypatch, tmp_path, current=current, last_roll=30)
    fetched = []
    house.ingest(_client(handler, fetched), {119: {1: 2025, 2: 2026}}, today)
    assert fetched[0] == house.URL.format(year=2025, roll=30 - house.REFRESH_RECENT + 1)


def test_house_file_from_the_wrong_congress_is_not_saved(monkeypatch, tmp_path):
    from yan.ingest import house

    monkeypatch.setattr(house, "RAW_DIR", tmp_path)
    client = _client(lambda request: httpx.Response(200, content=HOUSE_VOTE), [])
    with pytest.raises(ValueError, match="not from the 120th Congress"):
        house.ingest(client, {120: {1: 2027}})
    assert not (tmp_path / "house" / "2027").exists()


def _menu(numbers):
    votes = "".join(f"<vote><vote_number>{n:05d}</vote_number></vote>" for n in numbers)
    return f"<vote_summary><votes>{votes}</votes></vote_summary>".encode()


def _senate_setup(monkeypatch, tmp_path, current):
    from yan.ingest import senate

    monkeypatch.setattr(senate, "RAW_DIR", tmp_path)
    monkeypatch.setattr(senate, "CONGRESS", current)
    monkeypatch.setattr(senate, "REFRESH_RECENT", 2)
    session_dir = tmp_path / "senate" / "119" / "2"
    session_dir.mkdir(parents=True)
    (session_dir / "vote_menu.xml").write_bytes(_menu(range(1, 6)))
    for n in (1, 2, 4, 5):
        (session_dir / f"vote_119_2_{n:05d}.xml").write_bytes(b"<roll_call_vote/>")

    def handler(request):
        if "vote_menu" in request.url.path:
            return httpx.Response(200, content=_menu(range(1, 6)))
        return httpx.Response(200, content=b"<roll_call_vote/>")

    return senate, handler


def test_senate_past_congress_uses_its_saved_menu_and_fetches_only_missing_votes(monkeypatch, tmp_path):
    senate, handler = _senate_setup(monkeypatch, tmp_path, current=120)
    fetched = []
    senate.ingest(_client(handler, fetched), {119: {2: 2026}}, LONG_ENDED)
    assert fetched == [senate.VOTE_URL.format(congress=119, session=2, vote=3)]


@pytest.mark.parametrize("current, today", [(119, LONG_ENDED), (120, JUST_ENDED)])
def test_senate_current_or_just_ended_congress_fetches_its_menu_and_recent_votes(
        monkeypatch, tmp_path, current, today):
    senate, handler = _senate_setup(monkeypatch, tmp_path, current=current)
    fetched = []
    senate.ingest(_client(handler, fetched), {119: {2: 2026}}, today)
    assert fetched == [senate.MENU_URL.format(congress=119, session=2)] + [
        senate.VOTE_URL.format(congress=119, session=2, vote=n) for n in (3, 4, 5)]


def test_senate_past_congress_with_no_saved_menu_fetches_it(monkeypatch, tmp_path):
    senate, handler = _senate_setup(monkeypatch, tmp_path, current=120)
    fetched = []
    senate.ingest(_client(handler, fetched), {119: {1: 2025}}, LONG_ENDED)
    assert fetched[0] == senate.MENU_URL.format(congress=119, session=1)
    assert len(fetched) == 6
    assert (tmp_path / "senate" / "119" / "1" / "vote_menu.xml").exists()


def test_voted_bills_carry_their_votes_congress(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    (tmp_path / "house" / "2025").mkdir(parents=True)
    shutil.copy(FIXTURES / "house_2025_roll010.xml", tmp_path / "house" / "2025" / "roll010.xml")
    (tmp_path / "senate" / "119" / "1").mkdir(parents=True)
    shutil.copy(FIXTURES / "senate_119_1_00001.xml", tmp_path / "senate" / "119" / "1" / "vote_119_1_00001.xml")
    monkeypatch.setattr(congress_gov, "RAW_DIR", tmp_path)

    bills = congress_gov.voted_bills()
    assert bills and all(congress == 119 for congress, _, _ in bills)


class _BillClient:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None):
        self.urls.append(url)
        return httpx.Response(200, json={"bill": {}, "summaries": []}, request=httpx.Request("GET", url))


def test_bills_are_fetched_under_their_own_congress(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "RAW_DIR", tmp_path)
    monkeypatch.setattr(congress_gov, "CONGRESS", 120)
    monkeypatch.setattr(congress_gov, "CONGRESSES", {119: {1: 2025, 2: 2026}, 120: {1: 2027, 2: 2028}})
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: [])
    old = dt.date(2025, 3, 1)
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {
        (119, "hr", "1"): old, (119, "hr", "2"): old, (120, "hr", "1"): old,
    })
    # The 119th's H.R. 1 files are on disk and over a week old: a past Congress's
    # files aren't refreshed. The 120th's H.R. 1 is a different bill and gets its own.
    for kind in ("bills", "summaries"):
        path = congress_gov.raw_path(119, "hr", "1", kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        os.utime(path, (path.stat().st_mtime - 30 * 24 * 3600,) * 2)

    client = _BillClient()
    congress_gov.ingest(client, LONG_ENDED)

    assert client.urls == [
        congress_gov.BILL_URL.format(congress=119, bill_type="hr", bill_number="2"),
        congress_gov.SUMMARIES_URL.format(congress=119, bill_type="hr", bill_number="2"),
        congress_gov.BILL_URL.format(congress=120, bill_type="hr", bill_number="1"),
        congress_gov.SUMMARIES_URL.format(congress=120, bill_type="hr", bill_number="1"),
    ]
    assert congress_gov.raw_path(120, "hr", "1", "bills").exists()

    # Just after the 119th ended, its week-old H.R. 1 files are still refreshed.
    client = _BillClient()
    congress_gov.ingest(client, JUST_ENDED)
    assert congress_gov.BILL_URL.format(congress=119, bill_type="hr", bill_number="1") in client.urls


def test_a_bill_from_an_unlisted_congress_is_fetched_only_when_missing(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "RAW_DIR", tmp_path)
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: [])
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {(118, "hr", "1"): JUST_ENDED})
    path = congress_gov.raw_path(118, "hr", "1", "bills")
    path.parent.mkdir(parents=True)
    path.write_text("{}")

    client = _BillClient()
    congress_gov.ingest(client, JUST_ENDED)  # no KeyError
    assert client.urls == [congress_gov.SUMMARIES_URL.format(congress=118, bill_type="hr", bill_number="1")]


def _votes_json(out_dir, vote_ids):
    out_dir.mkdir(parents=True, exist_ok=True)
    votes = [{"vote_id": v, "congress": int(v[1:4])} for v in vote_ids]
    (out_dir / "votes.json").write_text(json.dumps({"votes": votes}))


def test_export_refuses_to_drop_a_past_congress_vote(monkeypatch, tmp_path):
    from yan.export import json_export

    monkeypatch.setattr(json_export, "CONGRESS", 120)
    _votes_json(tmp_path, ["h119-2-0300", "h120-1-0001"])
    with pytest.raises(RuntimeError, match="h119-2-0300"):
        json_export.check_past_votes_kept(tmp_path, [{"vote_id": "h120-1-0001"}])


def test_export_may_drop_a_current_congress_vote(monkeypatch, tmp_path):
    from yan.export import json_export

    monkeypatch.setattr(json_export, "CONGRESS", 120)
    _votes_json(tmp_path, ["h119-2-0300", "h120-1-0001"])
    json_export.check_past_votes_kept(tmp_path, [{"vote_id": "h119-2-0300"}])
    json_export.check_past_votes_kept(tmp_path / "empty", [])  # first run: no votes.json yet
