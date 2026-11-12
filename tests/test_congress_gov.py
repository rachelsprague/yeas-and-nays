import datetime as dt
import os

from yan.ingest.congress_gov import needs_fetch

TODAY = dt.date(2026, 11, 12)


def test_fetches_missing_files(tmp_path):
    assert needs_fetch(tmp_path / "hr1.json", last_vote=dt.date(2025, 3, 1), today=TODAY)


def test_refetches_bills_voted_on_recently_and_stale_files(tmp_path):
    path = tmp_path / "hr1.json"
    path.write_text("{}")
    assert needs_fetch(path, last_vote=TODAY - dt.timedelta(days=2), today=TODAY)
    assert not needs_fetch(path, last_vote=dt.date(2025, 3, 1), today=TODAY)

    week_old = path.stat().st_mtime - 8 * 24 * 3600
    os.utime(path, (week_old, week_old))
    assert needs_fetch(path, last_vote=dt.date(2025, 3, 1), today=TODAY)


def test_parse_bill_takes_the_sponsor_and_counts():
    from pathlib import Path

    from yan.stage.congress_gov import parse_bill

    path = Path(__file__).parent / "fixtures" / "congress_gov_bill_119_hr_1013.json"
    bill = parse_bill(path.read_bytes(), "119/bills/hr1013.json")
    assert bill["bill_type"] == "hr" and bill["bill_number"] == "1013" and bill["congress"] == "119"
    assert bill["sponsor_bioguide_id"] == "L000491"
    assert bill["sponsor_full_name"] == "Rep. Lucas, Frank D. [R-OK-3]"
    assert bill["cosponsor_count"] == "24"
    assert bill["introduced_date"] == "2025-02-05"
    assert bill["legislation_url"] == "https://www.congress.gov/bill/119th-congress/house-bill/1013"


class _StubResponse:
    def __init__(self, doc):
        self._doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self._doc


class _StubClient:
    """Serves a member's sponsored legislation in pages, like the API (count + offset)."""

    def __init__(self, items, page_size):
        self.items, self.page_size, self.calls = items, page_size, []

    def get(self, url, headers=None):
        from urllib.parse import parse_qs, urlparse

        assert headers == {"X-Api-Key": "k"} and "k" not in url  # key only in the header
        offset = int(parse_qs(urlparse(url).query)["offset"][0])
        self.calls.append(offset)
        page = self.items[offset:offset + self.page_size]
        return _StubResponse({"pagination": {"count": len(self.items)}, "sponsoredLegislation": page})


def test_fetch_sponsored_pages_through_and_keeps_this_congress_bills(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 2)
    items = [
        {"congress": 119, "type": "HR", "number": "1"},
        {"congress": 119, "number": "5", "amendmentNumber": "5"},  # amendment: no bill type
        {"congress": 118, "type": "HR", "number": "9"},
        {"congress": 119, "type": "HRES", "number": "2"},
        {"congress": 117, "type": "S", "number": "3"},
    ]
    client = _StubClient(items, page_size=2)
    doc = congress_gov.fetch_sponsored(client, "k", "M001184")
    assert client.calls == [0, 2, 4]
    assert [i["number"] for i in doc["sponsoredLegislation"]] == ["1", "2"]
