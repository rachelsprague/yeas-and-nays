import datetime as dt
import json
import os

import pytest

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


class _ActionsClient:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None):
        import httpx

        self.urls.append(url)
        return httpx.Response(200, json={"bill": {}, "summaries": [], "actions": []}, request=httpx.Request("GET", url))


def test_missing_actions_files_are_backfilled_a_few_per_run(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "RAW_DIR", tmp_path)
    monkeypatch.setattr(congress_gov, "ACTIONS_BACKFILL_PER_RUN", 2)
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: [])
    old, recent = dt.date(2025, 3, 1), TODAY - dt.timedelta(days=1)
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {
        (119, "hr", "1"): old, (119, "hr", "2"): old, (119, "hr", "3"): old, (119, "hr", "4"): recent,
    })
    # Every bill's details and summaries are on disk and fresh; only actions are missing.
    for number in "1234":
        for kind in ("bills", "summaries"):
            path = congress_gov.raw_path(119, "hr", number, kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")

    client = _ActionsClient()
    congress_gov.ingest(client, TODAY)
    actions = [u for u in client.urls if "/actions?" in u]
    # Two backfilled, then H.R. 4, voted on recently, past the cap.
    assert actions == [congress_gov.ACTIONS_URL.format(congress=119, bill_type="hr", bill_number=n, offset=0)
                       for n in "124"]

    client = _ActionsClient()
    congress_gov.ingest(client, TODAY)
    assert congress_gov.ACTIONS_URL.format(congress=119, bill_type="hr", bill_number="3", offset=0) in client.urls
    assert congress_gov.ACTIONS_URL.format(congress=119, bill_type="hr", bill_number="1", offset=0) not in client.urls


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


class _PagedActionsClient:
    """300 actions, served 250 per page."""

    def __init__(self):
        self.urls = []

    def get(self, url, headers=None):
        import httpx

        self.urls.append(url)
        offset = int(url.rsplit("offset=", 1)[1])
        page = [{"actionDate": "2025-01-03", "text": f"Action {i}"} for i in range(offset, min(offset + 250, 300))]
        doc = {"request": {"congress": "119", "billType": "hr", "billNumber": "1"},
               "actions": page, "pagination": {"count": 300}}
        return httpx.Response(200, json=doc, request=httpx.Request("GET", url))


def test_fetch_actions_reads_every_page():
    from yan.ingest.congress_gov import fetch_actions

    client = _PagedActionsClient()
    doc = json.loads(fetch_actions(client, "k", 119, "hr", "1"))
    assert [u.rsplit("offset=", 1)[1] for u in client.urls] == ["0", "250"]
    assert len(doc["actions"]) == 300 and doc["actions"][-1]["text"] == "Action 299"
    assert doc["request"]["billNumber"] == "1"


def test_fetch_actions_raises_on_a_later_page_without_a_count():
    import httpx

    from yan.ingest.congress_gov import fetch_actions

    class Client:
        def get(self, url, headers=None):
            first = url.endswith("offset=0")
            doc = {"request": {}, "actions": [{"text": "a"}] * (250 if first else 1)}
            if first:
                doc["pagination"] = {"count": 300}
            return httpx.Response(200, json=doc, request=httpx.Request("GET", url))

    with pytest.raises(ValueError, match="no pagination count"):
        fetch_actions(Client(), "k", 119, "hr", "1")


def test_fetch_actions_raises_on_a_response_without_actions(monkeypatch):
    import httpx

    from yan.ingest.congress_gov import fetch_actions

    class Client:
        def get(self, url, headers=None):
            return httpx.Response(200, json={"error": "x"}, request=httpx.Request("GET", url))

    with pytest.raises(ValueError, match="no 'actions'"):
        fetch_actions(Client(), "k", 119, "hr", "1")


def test_parse_actions_keeps_each_action_with_its_code_and_source():
    from pathlib import Path

    from yan.stage.congress_gov import parse_actions

    path = Path(__file__).parent / "fixtures" / "congress_gov_actions_119_hr_1.json"
    rows = parse_actions(path.read_bytes(), "119/actions/hr1.json")
    assert len(rows) == 59
    assert rows[0] == {
        "source_file": "119/actions/hr1.json", "congress": "119", "bill_type": "hr", "bill_number": "1",
        "action_date": "2025-07-04", "action_code": "E40000", "action_type": "President",
        "source_system_code": "9", "action_text": "Became Public Law No: 119-21.",
    }
    # Senate actions have no action code, and their source system has a name but no code.
    senate = [r for r in rows if r["action_code"] is None]
    assert senate and all(r["source_system_code"] is None for r in senate)


def test_parse_actions_logs_a_bill_with_more_actions_than_fetched(caplog):
    from yan.stage.congress_gov import parse_actions

    doc = {"request": {"congress": "119", "billType": "HR", "billNumber": "2"},
           "actions": [{"actionDate": "2025-01-03", "text": "Introduced in House"}], "pagination": {"count": 300}}
    rows = parse_actions(json.dumps(doc).encode(), "119/actions/hr2.json")
    assert rows[0]["bill_type"] == "hr" and rows[0]["source_system_code"] is None
    assert "1 of 300 actions fetched" in caplog.text


class _StubResponse:
    def __init__(self, doc):
        self._doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self._doc


class _StubClient:
    """Serves a member's sponsored or cosponsored legislation in pages, like the API
    (count + offset)."""

    def __init__(self, items, page_size):
        self.items, self.page_size, self.calls = items, page_size, []

    def get(self, url, headers=None):
        from urllib.parse import parse_qs, urlparse

        assert headers == {"X-Api-Key": "k"} and "k" not in url  # key only in the header
        parsed = urlparse(url)
        offset = int(parse_qs(parsed.query)["offset"][0])
        self.calls.append((parsed.path, offset))
        kind = parsed.path.rsplit("/", 1)[-1].removesuffix("-legislation")
        page = self.items[offset:offset + self.page_size]
        return _StubResponse({"pagination": {"count": len(self.items)}, f"{kind}Legislation": page})


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
    doc, _ = congress_gov.fetch_sponsored(client, "k", "M001184")
    assert [offset for _, offset in client.calls] == [0, 2, 4]
    assert [i["number"] for i in doc["sponsoredLegislation"]] == ["1", "2"]


def test_fetch_cosponsored_reads_every_page_and_counts_requests(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 2)
    # Not sorted by Congress (as the API returns it), so a page with no 119th items
    # doesn't mean the rest of the list has none.
    items = [
        {"congress": 119, "type": "S", "number": "7"},
        {"congress": 114, "type": "S", "number": "1"},
        {"congress": 96, "type": "S", "number": "2"},
        {"congress": 95, "number": "3", "amendmentNumber": "3"},
        {"congress": 119, "type": "SRES", "number": "4"},
    ]
    client = _StubClient(items, page_size=2)
    doc, requests = congress_gov.fetch_cosponsored(client, "k", "G000386")
    assert {path for path, _ in client.calls} == {"/v3/member/G000386/cosponsored-legislation"}
    assert requests == 3
    assert [i["number"] for i in doc["cosponsoredLegislation"]] == ["7", "4"]


def test_ingest_fetches_stalest_cosponsored_lists_within_the_budget(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {})
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: ["A1", "B2", "C3", "D4"])
    monkeypatch.setattr(congress_gov, "sponsored_path", lambda m: tmp_path / "sponsored" / f"{m}.json")
    monkeypatch.setattr(congress_gov, "fetch_sponsored", lambda *a: ({}, 1))
    monkeypatch.setattr(congress_gov, "cosponsored_path", lambda m: tmp_path / "cosponsored" / f"{m}.json")
    monkeypatch.setattr(congress_gov, "COSPONSORED_REQUEST_BUDGET", 3)

    # B2 is fresh (skipped); D4's list is older than C3's, and A1 has never been fetched.
    (tmp_path / "cosponsored").mkdir()
    week = 8 * 24 * 3600
    for member, age in [("B2", 0), ("C3", week), ("D4", 2 * week)]:
        path = tmp_path / "cosponsored" / f"{member}.json"
        path.write_text("{}")
        os.utime(path, (path.stat().st_mtime - age,) * 2)

    fetched = []

    def fake_fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 2

    monkeypatch.setattr(congress_gov, "fetch_cosponsored", fake_fetch)
    congress_gov.ingest(client=None)
    # Two lists use up the budget of 3 (2 requests each); C3 waits for the next run.
    assert fetched == ["A1", "D4"]


def _cosponsored_setup(monkeypatch, tmp_path, fetch):
    """Point cosponsored paths at tmp_path, stub the fetch, and drive time.monotonic() by hand."""
    from yan.ingest import congress_gov

    clock = {"now": 1000.0}
    monkeypatch.setattr(congress_gov.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(congress_gov, "cosponsored_path", lambda m: tmp_path / f"{m}.json")
    monkeypatch.setattr(congress_gov, "fetch_cosponsored", fetch)
    return congress_gov, clock


def test_cosponsored_lists_stop_starting_after_the_time_budget(monkeypatch, tmp_path):
    fetched = []

    def slow_fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        clock["now"] += 6 * 60  # each list takes 6 minutes
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 1

    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, slow_fetch)
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3"], TODAY, started=clock["now"])
    # A1 ends at 6 min, B2 starts before the 10-minute budget and ends at 12; C3 waits.
    assert fetched == ["A1", "B2"]


def test_a_list_bigger_than_the_request_budget_is_still_fetched(monkeypatch, tmp_path):
    fetched = []

    def big_fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 5

    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, big_fetch)
    monkeypatch.setattr(congress_gov, "COSPONSORED_REQUEST_BUDGET", 3)
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    # The budget only stops new lists from starting: A1 takes 5 requests against a budget
    # of 3 and is saved whole; B2 waits for the next run.
    assert fetched == ["A1"]
    assert (tmp_path / "A1.json").exists()


def test_cosponsored_lists_are_skipped_after_a_long_sponsored_refresh(monkeypatch, tmp_path):
    fetched = []
    congress_gov, clock = _cosponsored_setup(
        monkeypatch, tmp_path, lambda c, k, m: fetched.append(m) or ({}, 1))
    started = clock["now"] - 31 * 60  # the step has already run 31 minutes
    congress_gov.ingest_cosponsored(None, "k", ["A1"], TODAY, started=started)
    assert fetched == []


def test_a_failing_cosponsored_list_is_skipped_and_the_rest_fetched(monkeypatch, tmp_path):
    import httpx

    def fetch(client, key, bioguide_id):
        if bioguide_id == "A1":
            request = httpx.Request("GET", "https://api.congress.gov/v3/member/A1/cosponsored-legislation")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 1

    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, fetch)
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    assert not (tmp_path / "A1.json").exists()  # stays stale, retried next run
    assert (tmp_path / "B2.json").exists()


def _http_error(status):
    import httpx

    request = httpx.Request("GET", "https://api.congress.gov/v3/member/A1/cosponsored-legislation")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))


def _failing_fetch(errors, fetched):
    """A stub fetch that raises errors[member] for listed members and saves the rest."""
    def fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        if bioguide_id in errors:
            raise errors[bioguide_id]
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 1
    return fetch


@pytest.mark.parametrize("error", [ValueError("no cosponsoredLegislation"),
                                   json.JSONDecodeError("Expecting value", "<html>", 0)])
def test_a_list_with_a_bad_response_is_skipped_like_an_http_error(monkeypatch, tmp_path, error):
    fetched = []
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch({"A1": error}, fetched))
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    assert fetched == ["A1", "B2"]
    assert not (tmp_path / "A1.json").exists() and (tmp_path / "B2.json").exists()


def test_the_run_fails_when_every_list_tried_fails(monkeypatch, tmp_path):
    fetched = []
    errors = {m: ValueError("renamed key") for m in ["A1", "B2", "C3"]}
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch(errors, fetched))
    with pytest.raises(RuntimeError, match="3 cosponsored-legislation lists failed and none were fetched"):
        congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3", "D4"], TODAY, started=clock["now"])
    assert fetched == ["A1", "B2", "C3"]


def test_one_or_two_failed_lists_with_none_fetched_dont_fail_the_run(monkeypatch, tmp_path):
    # e.g. the last stale lists of a rotation during a short outage: the vote posts still go out.
    fetched = []
    errors = {"A1": _http_error(503), "B2": _http_error(503)}
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch(errors, fetched))
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    assert fetched == ["A1", "B2"]


def test_a_rate_limit_on_the_first_list_stops_without_failing_the_run(monkeypatch, tmp_path):
    fetched = []
    congress_gov, clock = _cosponsored_setup(
        monkeypatch, tmp_path, _failing_fetch({"A1": _http_error(429)}, fetched))
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    assert fetched == ["A1"]


def test_a_rate_limit_after_two_failures_doesnt_fail_the_run(monkeypatch, tmp_path):
    fetched = []
    errors = {"A1": _http_error(503), "B2": _http_error(503), "C3": _http_error(429)}
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch(errors, fetched))
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3", "D4"], TODAY, started=clock["now"])
    assert fetched == ["A1", "B2", "C3"]


def test_a_rate_limited_page_from_the_api_stops_the_lists(monkeypatch, tmp_path):
    import httpx

    from yan.ingest import congress_gov

    class _RateLimited:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None):
            self.calls += 1
            return httpx.Response(429, request=httpx.Request("GET", url))

    monkeypatch.setattr(congress_gov, "cosponsored_path", lambda m: tmp_path / f"{m}.json")
    client = _RateLimited()
    congress_gov.ingest_cosponsored(client, "k", ["A1", "B2"], TODAY, started=congress_gov.time.monotonic())
    assert client.calls == 1
    assert not (tmp_path / "A1.json").exists()


def test_an_error_other_than_http_or_a_bad_response_stops_the_run(monkeypatch, tmp_path):
    fetched = []
    congress_gov, clock = _cosponsored_setup(
        monkeypatch, tmp_path, _failing_fetch({"A1": OSError("disk full")}, fetched))
    with pytest.raises(OSError):
        congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])
    assert fetched == ["A1"]


def test_a_fetch_result_that_cant_be_unpacked_isnt_logged_as_a_failed_list(monkeypatch, tmp_path):
    # The unpack is outside the try, so a bug here raises instead of reading as an API error.
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, lambda c, k, m: ({},))
    with pytest.raises(ValueError, match="unpack"):
        congress_gov.ingest_cosponsored(None, "k", ["A1", "B2"], TODAY, started=clock["now"])


def test_a_rate_limit_stops_the_rest_of_the_lists(monkeypatch, tmp_path):
    fetched = []
    congress_gov, clock = _cosponsored_setup(
        monkeypatch, tmp_path, _failing_fetch({"B2": _http_error(429)}, fetched))
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3"], TODAY, started=clock["now"])
    assert fetched == ["A1", "B2"]


def test_several_failures_in_a_row_stop_the_rest_of_the_lists(monkeypatch, tmp_path):
    fetched = []
    # B2 fails, C3 resets the count, then D4, E5 and F6 fail in a row; G7 waits.
    errors = {m: _http_error(500) for m in ["B2", "D4", "E5", "F6"]}
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch(errors, fetched))
    members = ["A1", "B2", "C3", "D4", "E5", "F6", "G7"]
    congress_gov.ingest_cosponsored(None, "k", members, TODAY, started=clock["now"])
    assert fetched == members[:-1]


def test_a_failed_list_counts_every_request_it_made(monkeypatch, tmp_path):
    fetched = []
    error = _http_error(500)
    error.requests = 3  # failed on its third page
    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, _failing_fetch({"A1": error}, fetched))
    monkeypatch.setattr(congress_gov, "COSPONSORED_REQUEST_BUDGET", 4)
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3"], TODAY, started=clock["now"])
    # A1's 3 requests and B2's 1 use the budget of 4; C3 waits.
    assert fetched == ["A1", "B2"]


def test_the_time_budget_counts_from_when_cosponsored_lists_start(monkeypatch, tmp_path):
    fetched = []

    def slow_fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        clock["now"] += 6 * 60
        return {"bioguideId": bioguide_id, "cosponsoredLegislation": []}, 1

    congress_gov, clock = _cosponsored_setup(monkeypatch, tmp_path, slow_fetch)
    started = clock["now"] - 29 * 60  # the process has run 29 minutes: not skipped yet
    congress_gov.ingest_cosponsored(None, "k", ["A1", "B2", "C3"], TODAY, started=started)
    # The 10-minute budget starts now, not at `started`: A1 and B2 start within it.
    assert fetched == ["A1", "B2"]


def test_ingest_skips_cosponsored_lists_by_the_process_start(monkeypatch, tmp_path):
    import yan

    fetched = []
    congress_gov, clock = _cosponsored_setup(
        monkeypatch, tmp_path, lambda c, k, m: fetched.append(m) or ({}, 1))
    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {})
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: ["A1"])
    monkeypatch.setattr(congress_gov, "sponsored_path", lambda m: tmp_path / "sponsored" / f"{m}.json")
    monkeypatch.setattr(congress_gov, "fetch_sponsored", lambda *a: ({}, 1))
    monkeypatch.setattr(yan, "STARTED", clock["now"] - 31 * 60)  # earlier ingest steps took 31 minutes
    congress_gov.ingest(client=None)
    assert fetched == []


def test_ingest_fetches_sponsored_lists_then_cosponsored(monkeypatch, tmp_path):
    import yan
    from yan.ingest import congress_gov

    calls = []

    def fetch(kind):
        def stub(client, key, bioguide_id):
            calls.append((kind, bioguide_id))
            return {"bioguideId": bioguide_id, f"{kind}Legislation": []}, 1
        return stub

    monkeypatch.setenv("CONGRESS_API_KEY", "k")
    monkeypatch.setattr(congress_gov, "voted_bills", lambda: {})
    monkeypatch.setattr(congress_gov, "members_in_congress", lambda: ["A1", "B2"])
    monkeypatch.setattr(congress_gov, "sponsored_path", lambda m: tmp_path / "sponsored" / f"{m}.json")
    monkeypatch.setattr(congress_gov, "cosponsored_path", lambda m: tmp_path / "cosponsored" / f"{m}.json")
    monkeypatch.setattr(congress_gov, "fetch_sponsored", fetch("sponsored"))
    monkeypatch.setattr(congress_gov, "fetch_cosponsored", fetch("cosponsored"))
    monkeypatch.setattr(yan, "STARTED", congress_gov.time.monotonic())
    congress_gov.ingest(client=None)
    assert calls == [("sponsored", "A1"), ("sponsored", "B2"), ("cosponsored", "A1"), ("cosponsored", "B2")]
    for kind in ["sponsored", "cosponsored"]:
        assert json.loads((tmp_path / kind / "B2.json").read_text()) == {
            "bioguideId": "B2", f"{kind}Legislation": []}


class _ShapeClient:
    """Serves a good first page of a two-page list, then `second` as page two."""

    def __init__(self, second):
        self.second, self.calls = second, 0

    def get(self, url, headers=None):
        self.calls += 1
        if self.calls == 1:
            return _StubResponse({"pagination": {"count": 2},
                                  "cosponsoredLegislation": [{"congress": 119, "type": "S", "number": "1"}]})
        return _StubResponse(self.second)


@pytest.mark.parametrize("second", [
    None,
    [],
    {"pagination": None, "cosponsoredLegislation": [{"congress": 119, "type": "S", "number": "2"}]},
    {"pagination": {"count": None}, "cosponsoredLegislation": []},
    {"pagination": {"count": "2"}, "cosponsoredLegislation": []},
    {"pagination": {"count": True}, "cosponsoredLegislation": []},
    {"cosponsoredLegislation": [{"congress": 119, "type": "S", "number": "2"}]},
    {"cosponsoredLegislation": []},  # an empty later page could hide a list cut short
    {"pagination": {"count": 2}, "cosponsoredLegislation": []},  # empty short of its count
    {"pagination": {"count": 2}},
    {"pagination": {"count": 2}, "cosponsoredLegislation": None},
    {"pagination": {"count": 2}, "cosponsoredLegislation": ["S 2"]},
])
def test_a_malformed_member_list_response_raises_value_error_with_its_requests(monkeypatch, second):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    with pytest.raises(ValueError) as caught:
        congress_gov.fetch_cosponsored(_ShapeClient(second), "k", "A000001")
    assert caught.value.requests == 2


def test_a_request_that_raises_before_a_response_still_counts(monkeypatch):
    import httpx

    from yan.ingest import congress_gov

    class _Unreachable:
        def get(self, url, headers=None):
            raise httpx.ConnectError("unreachable")

    with pytest.raises(httpx.ConnectError) as caught:
        congress_gov.fetch_cosponsored(_Unreachable(), "k", "A000001")
    assert caught.value.requests == 1


class _ChangingClient(_StubClient):
    """A _StubClient whose list becomes `changes[n]` just before its nth request (from 1)."""

    def __init__(self, items, page_size, changes):
        super().__init__(items, page_size)
        self.changes = changes

    def get(self, url, headers=None):
        self.items = self.changes.get(len(self.calls) + 1, self.items)
        return super().get(url, headers)


def _bill(number):
    return {"congress": 119, "type": "S", "number": number}


def test_an_empty_later_page_ends_a_list_that_shrank_between_requests(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    # S 2 is removed before page two, which comes back empty with a count of 1; the
    # count changed, so the list is fetched again and reads S 1 alone.
    client = _ChangingClient([_bill("1"), _bill("2")], page_size=1, changes={2: [_bill("1")]})
    doc, requests = congress_gov.fetch_cosponsored(client, "k", "A000001")
    assert [i["number"] for i in doc["cosponsoredLegislation"]] == ["1"]
    assert [offset for _, offset in client.calls] == [0, 1, 0]
    assert requests == 3


def test_a_list_whose_count_changes_mid_fetch_is_fetched_again(monkeypatch, caplog):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 2)
    # S 9 is removed after page one, so S 5 moves up onto page one and is skipped by
    # page two; the second pass reads the list as it now stands.
    before = [_bill("1"), _bill("9"), _bill("5"), _bill("4")]
    after = [_bill("1"), _bill("5"), _bill("4")]
    client = _ChangingClient(before, page_size=2, changes={2: after})
    with caplog.at_level("INFO", logger=congress_gov.log.name):
        doc, requests = congress_gov.fetch_cosponsored(client, "k", "A000001")
    assert [i["number"] for i in doc["cosponsoredLegislation"]] == ["1", "5", "4"]
    assert [offset for _, offset in client.calls] == [0, 2, 0, 2]
    assert requests == 4
    assert "count changed from 4 to 3" in caplog.text


def test_a_list_whose_count_changes_on_both_passes_keeps_the_second(monkeypatch, caplog):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    # A bill is added at the front during each pass: no third pass, and the second pass's
    # result is kept (S 5, added during it, is missed until the next run).
    client = _ChangingClient([_bill("1"), _bill("2")], page_size=1, changes={
        2: [_bill("3"), _bill("1"), _bill("2")],
        4: [_bill("4"), _bill("3"), _bill("1"), _bill("2")],
        5: [_bill("5"), _bill("4"), _bill("3"), _bill("1"), _bill("2")],
    })
    with caplog.at_level("WARNING", logger=congress_gov.log.name):
        doc, requests = congress_gov.fetch_cosponsored(client, "k", "A000001")
    assert [offset for _, offset in client.calls] == [0, 1, 2, 0, 1, 2, 3, 4]
    assert [i["number"] for i in doc["cosponsoredLegislation"]] == ["4", "3", "1", "2"]
    assert requests == 8
    assert "changed from 4 to 5 again" in caplog.text


def test_a_list_with_a_steady_count_is_fetched_once(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    client = _StubClient([_bill("1"), _bill("2"), _bill("3")], page_size=1)
    _, requests = congress_gov.fetch_cosponsored(client, "k", "A000001")
    assert requests == 3 and len(client.calls) == 3


def test_a_failure_on_the_second_pass_counts_both_passes(monkeypatch):
    import httpx

    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)

    class _FailsOnRefetch(_ChangingClient):
        def get(self, url, headers=None):
            if len(self.calls) == 2:  # the second pass's first request
                self.calls.append(None)
                return httpx.Response(503, request=httpx.Request("GET", url))
            return super().get(url, headers)

    client = _FailsOnRefetch([_bill("1"), _bill("2")], page_size=1, changes={2: [_bill("1")]})
    with pytest.raises(httpx.HTTPStatusError) as caught:
        congress_gov.fetch_cosponsored(client, "k", "A000001")
    assert caught.value.requests == 3


def test_an_empty_first_page_short_of_its_count_raises():
    from yan.ingest import congress_gov

    class _EmptyFirst:
        def get(self, url, headers=None):
            return _StubResponse({"pagination": {"count": 3}, "cosponsoredLegislation": []})

    with pytest.raises(ValueError, match="empty page") as caught:
        congress_gov.fetch_cosponsored(_EmptyFirst(), "k", "A000001")
    assert caught.value.requests == 1


class _FailingLaterPage(_ShapeClient):
    """Serves a good first page of a two-page list, then an HTTP `status` for page two."""

    def __init__(self, status):
        super().__init__(None)
        self.status = status

    def get(self, url, headers=None):
        import httpx

        if self.calls == 0:
            return super().get(url, headers)
        self.calls += 1
        return httpx.Response(self.status, request=httpx.Request("GET", url))


@pytest.mark.parametrize("status", [429, 503])
def test_a_failed_later_page_raises_with_every_request_counted(monkeypatch, status):
    import httpx

    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        congress_gov.fetch_cosponsored(_FailingLaterPage(status), "k", "A000001")
    assert caught.value.response.status_code == status
    assert caught.value.requests == 2


def test_a_rate_limit_on_a_later_page_saves_nothing_and_stops_the_lists(monkeypatch, tmp_path):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 1)
    monkeypatch.setattr(congress_gov, "cosponsored_path", lambda m: tmp_path / f"{m}.json")
    client = _FailingLaterPage(429)
    congress_gov.ingest_cosponsored(client, "k", ["A1", "B2"], TODAY, started=congress_gov.time.monotonic())
    assert client.calls == 2  # B2 never started
    assert not (tmp_path / "A1.json").exists()


def _sponsored_setup(monkeypatch, tmp_path, errors, fetched):
    """Point sponsored paths at tmp_path and stub the fetch to raise errors[member]."""
    from yan.ingest import congress_gov

    def fetch(client, key, bioguide_id):
        fetched.append(bioguide_id)
        if bioguide_id in errors:
            raise errors[bioguide_id]
        return {"bioguideId": bioguide_id, "sponsoredLegislation": []}, 1

    monkeypatch.setattr(congress_gov, "sponsored_path", lambda m: tmp_path / f"{m}.json")
    monkeypatch.setattr(congress_gov, "fetch_sponsored", fetch)
    return congress_gov


@pytest.mark.parametrize("error", [ValueError("empty page at offset 250 of 600"), _http_error(503)])
def test_a_failing_sponsored_list_keeps_its_old_file_and_the_rest_are_fetched(monkeypatch, tmp_path, error):
    fetched = []
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, {"A1": error}, fetched)
    (tmp_path / "A1.json").write_text("old")
    congress_gov.ingest_sponsored(None, "k", ["A1", "B2"], ["A1", "B2"])
    assert fetched == ["A1", "B2"]
    assert (tmp_path / "A1.json").read_text() == "old"
    assert (tmp_path / "B2.json").exists()


def test_a_rate_limit_stops_the_sponsored_lists_without_failing_the_run(monkeypatch, tmp_path):
    fetched = []
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, {"A1": _http_error(429)}, fetched)
    congress_gov.ingest_sponsored(None, "k", ["A1", "B2"], ["A1", "B2"])
    assert fetched == ["A1"]


def test_the_run_fails_when_every_sponsored_list_tried_fails(monkeypatch, tmp_path):
    fetched = []
    errors = {m: _http_error(503) for m in ["A1", "B2", "C3", "D4"]}
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, errors, fetched)
    with pytest.raises(RuntimeError, match="3 sponsored-legislation lists failed"):
        congress_gov.ingest_sponsored(None, "k", list(errors), list(errors))
    assert fetched == ["A1", "B2", "C3"]


def test_one_or_two_failed_sponsored_lists_with_none_fetched_dont_fail_the_run(monkeypatch, tmp_path):
    fetched = []
    errors = {m: _http_error(503) for m in ["A1", "B2"]}
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, errors, fetched)
    congress_gov.ingest_sponsored(None, "k", list(errors), list(errors))
    assert fetched == ["A1", "B2"]


def test_a_rate_limit_after_two_sponsored_failures_doesnt_fail_the_run(monkeypatch, tmp_path):
    fetched = []
    errors = {"A1": _http_error(503), "B2": _http_error(503), "C3": _http_error(429)}
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, errors, fetched)
    congress_gov.ingest_sponsored(None, "k", [*errors, "D4"], [*errors, "D4"])
    assert fetched == ["A1", "B2", "C3"]


def test_a_fetched_sponsored_list_resets_the_failures_in_a_row(monkeypatch, tmp_path):
    fetched = []
    errors = {m: _http_error(503) for m in ["A1", "B2", "D4", "E5"]}
    members = ["A1", "B2", "C3", "D4", "E5", "F6"]
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, errors, fetched)
    congress_gov.ingest_sponsored(None, "k", members, members)
    assert fetched == members


def test_a_sponsored_failure_after_a_fetched_list_doesnt_fail_the_run(monkeypatch, tmp_path):
    fetched = []
    errors = {m: _http_error(503) for m in ["B2", "C3", "D4"]}
    congress_gov = _sponsored_setup(monkeypatch, tmp_path, errors, fetched)
    congress_gov.ingest_sponsored(None, "k", ["A1", *errors], ["A1", *errors])
    assert fetched == ["A1", "B2", "C3", "D4"]


@pytest.mark.parametrize("doc", [{"cosponsoredLegislation": []},
                                 {"pagination": None, "cosponsoredLegislation": []}])
def test_an_empty_list_with_no_pagination_reads_as_empty(doc):
    from yan.ingest import congress_gov

    class _OnePage:
        def get(self, url, headers=None):
            return _StubResponse(doc)

    result, requests = congress_gov.fetch_cosponsored(_OnePage(), "k", "A000001")
    assert result["cosponsoredLegislation"] == [] and requests == 1


def test_fetch_sponsored_drops_an_item_repeated_across_pages(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 2)
    # A bill introduced between page requests pushes HR 2 from page 1 onto page 2.
    items = [
        {"congress": 119, "type": "HR", "number": "3"},
        {"congress": 119, "type": "HR", "number": "2"},
        {"congress": 119, "type": "HR", "number": "2"},
        {"congress": 119, "type": "HR", "number": "1"},
    ]
    doc, _ = congress_gov.fetch_sponsored(_StubClient(items, page_size=2), "k", "M001184")
    assert [i["number"] for i in doc["sponsoredLegislation"]] == ["3", "2", "1"]


def test_members_in_congress_keeps_terms_that_reach_into_this_congress(monkeypatch):
    from yan.ingest import congress_gov

    terms = [
        {"bioguide_id": "B000002", "term_end": "2027-01-03"},
        {"bioguide_id": "A000001", "term_end": "2031-01-03"},
        {"bioguide_id": "A000001", "term_end": "2025-01-03"},  # earlier term, same member
        {"bioguide_id": "C000003", "term_end": "2025-01-03"},  # ended as this Congress began
        {"bioguide_id": "D000004", "term_end": "2023-01-03"},
        {"bioguide_id": "E000005", "term_end": None},  # no end date: ongoing
    ]
    monkeypatch.setattr(congress_gov.legislators, "parse_dir", lambda _: ([], terms, []))
    assert congress_gov.members_in_congress() == ["A000001", "B000002", "E000005"]


def test_members_in_congress_checks_an_open_ended_term_against_its_start(monkeypatch):
    from yan.ingest import congress_gov

    terms = [
        {"bioguide_id": "A000001", "term_start": "2025-01-03", "term_end": None},
        {"bioguide_id": "B000002", "term_start": "2027-01-03", "term_end": None},  # starts as the next Congress begins
        {"bioguide_id": "C000003", "term_start": "2029-01-03", "term_end": "2031-01-03"},
    ]
    monkeypatch.setattr(congress_gov.legislators, "parse_dir", lambda _: ([], terms, []))
    assert congress_gov.members_in_congress() == ["A000001"]


def test_members_in_congress_keeps_a_term_with_no_start_date(monkeypatch):
    from yan.ingest import congress_gov

    terms = [
        {"bioguide_id": "A000001", "term_start": None, "term_end": "2027-01-03"},
        {"bioguide_id": "B000002", "term_start": None, "term_end": "2023-01-03"},
    ]
    monkeypatch.setattr(congress_gov.legislators, "parse_dir", lambda _: ([], terms, []))
    assert congress_gov.members_in_congress() == ["A000001"]


def test_members_in_congress_treats_a_malformed_date_as_missing(monkeypatch, caplog):
    from yan.ingest import congress_gov

    terms = [
        {"bioguide_id": "A000001", "term_start": "2025-01-03", "term_end": "Jan 3, 2027"},  # read as ongoing
        {"bioguide_id": "B000002", "term_start": "2025-13-01", "term_end": "2027-01-03"},
        {"bioguide_id": "C000003", "term_start": "2023-01-03", "term_end": "2025-1-3"},  # read as ongoing
        {"bioguide_id": "D000004", "term_start": "not a date", "term_end": "2023-01-03"},  # still ended
    ]
    monkeypatch.setattr(congress_gov.legislators, "parse_dir", lambda _: ([], terms, []))
    assert congress_gov.members_in_congress() == ["A000001", "B000002", "C000003"]
    assert caplog.text.count("treating it as missing") == 4
    assert "'A000001' has a malformed term_end 'Jan 3, 2027'" in caplog.text


def test_members_in_congress_treats_a_non_string_date_as_missing(monkeypatch, caplog):
    from yan.ingest import congress_gov

    terms = [
        {"bioguide_id": "A000001", "term_start": 2025, "term_end": "2027-01-03"},
        {"bioguide_id": "B000002", "term_start": "2019-01-03", "term_end": dt.date(2021, 1, 3)},  # read as ongoing
    ]
    monkeypatch.setattr(congress_gov.legislators, "parse_dir", lambda _: ([], terms, []))
    assert congress_gov.members_in_congress() == ["A000001", "B000002"]
    assert caplog.text.count("treating it as missing") == 2
    assert "'A000001' has a malformed term_start 2025" in caplog.text


def test_fetch_sponsored_keeps_a_bill_type_or_congress_that_differs(monkeypatch):
    from yan.ingest import congress_gov

    monkeypatch.setattr(congress_gov, "PAGE_SIZE", 2)
    items = [
        {"congress": 119, "type": "HR", "number": "2"},
        {"congress": 119, "type": "HRES", "number": "2"},  # same number, another type: not a repeat
        {"congress": 118, "type": "S", "number": "5"},  # an earlier Congress's S 5 doesn't hide this one's
        {"congress": 119, "type": "S", "number": "5"},
    ]
    doc, _ = congress_gov.fetch_sponsored(_StubClient(items, page_size=2), "k", "M001184")
    assert [(i["type"], i["number"]) for i in doc["sponsoredLegislation"]] == [
        ("HR", "2"), ("HRES", "2"), ("S", "5")]


def test_member_list_rows_flattens_each_item():
    from yan.stage.congress_gov import member_list_rows

    doc = {"bioguideId": "M001184", "sponsoredLegislation": [
        {"congress": 119, "type": "HRES", "number": 12, "title": "Original title",
         "latestTitle": "Latest title", "introducedDate": "2025-01-09",
         "latestAction": {"actionDate": "2025-02-01", "text": "Referred to committee."},
         "policyArea": {"name": "Taxation"}},
        {"congress": 119, "type": "S", "number": "4", "title": "Only title",
         "latestAction": None, "policyArea": None},
    ]}
    rows = member_list_rows(doc, "119/sponsored/M001184.json", "sponsoredLegislation")
    assert rows[0] == {
        "source_file": "119/sponsored/M001184.json", "bioguide_id": "M001184", "congress": "119",
        "bill_type": "hres", "bill_number": "12", "title": "Latest title", "introduced_date": "2025-01-09",
        "latest_action_date": "2025-02-01", "latest_action_text": "Referred to committee.",
        "policy_area": "Taxation",
    }
    assert rows[1]["title"] == "Only title"
    assert rows[1]["latest_action_date"] is None and rows[1]["policy_area"] is None


def test_member_list_rows_drops_a_repeat_from_an_older_cached_file():
    from yan.stage.congress_gov import member_list_rows

    # Files cached before the fetch dropped repeats can hold one.
    doc = {"bioguideId": "M001184", "sponsoredLegislation": [
        {"congress": 119, "type": "HR", "number": "2", "title": "First"},
        {"congress": 119, "type": "HR", "number": 2, "title": "Repeat"},
        {"congress": 119, "type": "HRES", "number": "2", "title": "Another type"},
    ]}
    rows = member_list_rows(doc, "119/sponsored/M001184.json", "sponsoredLegislation")
    assert [(r["bill_type"], r["bill_number"], r["title"]) for r in rows] == [
        ("hr", "2", "First"), ("hres", "2", "Another type")]


def test_parse_sponsored_dir_records_every_fetched_list_even_when_empty(tmp_path):
    from yan.stage.congress_gov import parse_sponsored_dir

    folder = tmp_path / "119" / "sponsored"
    folder.mkdir(parents=True)
    (folder / "A1.json").write_text(json.dumps({"bioguideId": "A1", "congress": 119, "sponsoredLegislation": [
        {"congress": 119, "type": "HR", "number": 4, "title": "A title"},
    ]}))
    (folder / "B2.json").write_text(json.dumps({"bioguideId": "B2", "congress": 119, "sponsoredLegislation": []}))

    rows, lists = parse_sponsored_dir(tmp_path)
    assert [(r["bioguide_id"], r["bill_type"], r["bill_number"]) for r in rows] == [("A1", "hr", "4")]
    assert lists == [
        {"source_file": "119/sponsored/A1.json", "bioguide_id": "A1", "congress": "119", "bill_count": "1"},
        {"source_file": "119/sponsored/B2.json", "bioguide_id": "B2", "congress": "119", "bill_count": "0"},
    ]


def test_parse_cosponsored_dir_records_every_fetched_list_even_when_empty(tmp_path):
    from yan.stage.congress_gov import parse_cosponsored_dir

    folder = tmp_path / "119" / "cosponsored"
    folder.mkdir(parents=True)
    (folder / "A1.json").write_text(json.dumps({"bioguideId": "A1", "congress": 119, "cosponsoredLegislation": [
        {"congress": 119, "type": "S", "number": 7, "title": "A title"},
    ]}))
    (folder / "B2.json").write_text(json.dumps({"bioguideId": "B2", "congress": 119, "cosponsoredLegislation": []}))

    rows, lists = parse_cosponsored_dir(tmp_path)
    assert [(r["bioguide_id"], r["bill_type"], r["bill_number"]) for r in rows] == [("A1", "s", "7")]
    assert lists == [
        {"source_file": "119/cosponsored/A1.json", "bioguide_id": "A1", "congress": "119", "bill_count": "1"},
        {"source_file": "119/cosponsored/B2.json", "bioguide_id": "B2", "congress": "119", "bill_count": "0"},
    ]
