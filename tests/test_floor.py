import datetime as dt
from pathlib import Path

import httpx

from yan.http import Client
from yan.ingest import floor as ingest
from yan.stage.floor import parse_house_week, parse_senate_day, parse_session_days

FIXTURES = Path(__file__).parent / "fixtures"


def test_house_week_rows_are_floor_items_not_subitems():
    rows = parse_house_week((FIXTURES / "house_floor_2026-11-09.xml").read_bytes(), "house/2026-11-09.xml")

    assert [r["legis_num"] for r in rows] == ["H.R. 3978", "H.R. 5549", "H.R. 1013", "H. Res. 1650"]
    first = rows[0]
    assert (first["congress"], first["week_date"], first["item_id"]) == ("119", "2026-11-09", "409813")
    assert first["category"] == "Items that may be considered under suspension of the rules"
    assert first["floor_text"].startswith("Nuclear REFUEL")
    assert first["remove_date"] is None


def test_house_week_keeps_the_remove_date():
    content = b"""<floorschedule congress-num="119" week-date="2026-11-16">
      <category type="Items that may be considered pursuant to a rule" sort-order="2"><floor-items>
        <floor-item id="7" sort-order="1" remove-date="2026-11-17T10:00:00.000"><legis-num>H.R. 1</legis-num>
          <floor-text>Example Act</floor-text></floor-item>
      </floor-items></category></floorschedule>"""
    [row] = parse_house_week(content, "house/2026-11-16.xml")
    assert (row["category_order"], row["remove_date"]) == ("2", "2026-11-17T10:00:00.000")


def test_senate_day_has_a_row_per_status_line_including_amendments():
    rows = parse_senate_day((FIXTURES / "senate_floor_2026-11-11.xml").read_bytes(), "senate/2026-11-11.xml")

    bill = [r for r in rows if r["docnum"] == "H.R. 2347"]
    assert [r["status_text"] for r in bill] == [
        "Considered by Senate.",
        "Cloture motion on the measure presented in Senate.",
    ]
    assert [r["status_order"] for r in bill] == ["0", "1"]
    assert bill[0]["activity_date"] == "2026-11-11"
    # Wrapped titles lose the space the line break left before the final period.
    assert bill[0]["document_title"].endswith("sexual acts or sexual contact.")

    [amendment] = [r for r in rows if r["docnum"] == "S.Amdt. 6883" and "Cloture" in r["status_text"]]
    assert (amendment["document_prefix"], amendment["amends"]) == ("SA", "Amendment to H.R. 2347")
    assert amendment["status_text"] == "Cloture motion on amendment SA 6883 presented in Senate."

    [nomination] = [r for r in rows if r["docnum"] == "PN1272-3" and "Cloture" in r["status_text"]]
    assert nomination["status_text"] == "Cloture motion presented in Senate."
    assert nomination["document_title"].startswith("Daniel Lewis Ballou, of Kentucky")


SESSION_DAYS = b"""<?xml version="1.0" encoding="UTF-8"?><CongressSessionDayConvenings Congress="119" SessionNumber="2">
  <LegislativeDay LegislativeDayDate="2026-11-11T00:00:00-05:00"><SessionDay>
    <ConveneDate>2026-11-11T12:00:00-05:00</ConveneDate><AdjournDate>2026-11-11T16:05:00-05:00</AdjournDate>
    <NextConveneDate>2026-11-12T12:00:00-05:00</NextConveneDate></SessionDay></LegislativeDay>
  <LegislativeDay LegislativeDayDate="2026-11-12T00:00:00-05:00"><SessionDay>
    <ConveneDate>2026-11-12T12:00:00-05:00</ConveneDate><AdjournDate>2026-11-12T16:52:00-05:00</AdjournDate>
    <NextConveneDate>2026-11-16T15:00:00-05:00</NextConveneDate></SessionDay></LegislativeDay>
</CongressSessionDayConvenings>"""


def test_session_days():
    rows = parse_session_days(SESSION_DAYS, "senate/session_days.xml")
    assert rows[-1]["legislative_day"] == "2026-11-12"
    assert rows[-1]["next_convene_time"] == "2026-11-16T15:00:00-05:00"
    assert ingest.session_days(SESSION_DAYS) == [dt.date(2026, 11, 11), dt.date(2026, 11, 12)]


def test_week_start_is_monday():
    assert ingest.week_start(dt.date(2026, 11, 12)) == dt.date(2026, 11, 9)
    assert ingest.week_start(dt.date(2026, 11, 16)) == dt.date(2026, 11, 16)


def _client(routes: dict[str, httpx.Response]) -> Client:
    def handler(request):
        return routes.get(str(request.url), httpx.Response(200, text="<html>not found</html>"))
    return Client(delay=0, transport=httpx.MockTransport(handler))


def test_ingest_house_saves_published_weeks_and_prunes_old_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path)
    (tmp_path / "2026-11-02.xml").write_text("old week")
    (tmp_path / "2026-11-16.xml").write_text("kept until refetched")
    week = (FIXTURES / "house_floor_2026-11-09.xml").read_bytes()
    client = _client({ingest.HOUSE_URL.format(week=dt.date(2026, 11, 9)): httpx.Response(200, content=week)})

    ingest.ingest_house(client, dt.date(2026, 11, 12))

    # Next week isn't published (an HTML page): the copy on disk stays, last week's is gone.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-09.xml", "2026-11-16.xml"]
    assert (tmp_path / "2026-11-09.xml").read_bytes() == week


def test_an_error_on_this_weeks_house_file_still_fetches_next_week(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path)
    monkeypatch.setattr("yan.http.RETRY_BACKOFF_SECONDS", [])
    week = (FIXTURES / "house_floor_2026-11-09.xml").read_bytes()
    client = _client({
        ingest.HOUSE_URL.format(week=dt.date(2026, 11, 9)): httpx.Response(500),
        ingest.HOUSE_URL.format(week=dt.date(2026, 11, 16)): httpx.Response(200, content=week),
    })

    ingest.ingest_house(client, dt.date(2026, 11, 12))

    assert [p.name for p in tmp_path.iterdir()] == ["2026-11-16.xml"]
    assert "house floor schedule for week of 2026-11-09 not updated" in caplog.text


def test_a_404_is_not_published_rather_than_an_error(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path)
    client = _client({ingest.HOUSE_URL.format(week=dt.date(2026, 11, 9)): httpx.Response(404)})

    with caplog.at_level("INFO"):
        ingest.ingest_house(client, dt.date(2026, 11, 12))

    assert "week of 2026-11-09: not published" in caplog.text
    assert "not updated" not in caplog.text


def test_ingest_senate_fetches_recent_days_skips_unpublished_and_prunes(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path)
    (tmp_path / "2026-10-01.xml").write_text("out of the window")
    day = (FIXTURES / "senate_floor_2026-11-11.xml").read_bytes()
    client = _client({
        ingest.SENATE_DAYS_URL: httpx.Response(200, content=SESSION_DAYS),
        ingest.SENATE_DAY_URL.format(day=dt.date(2026, 11, 11)): httpx.Response(200, content=day),
    })

    ingest.ingest_senate(client, dt.date(2026, 11, 12))

    # Nov. 12 isn't posted yet (senate.gov answers with an HTML page).
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-11.xml", "session_days.xml"]


def test_a_malformed_or_wrong_congress_file_is_not_saved(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path / "house")
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path / "senate")
    week = (FIXTURES / "house_floor_2026-11-09.xml").read_bytes().replace(b'congress-num="119"', b'congress-num="120"')
    client = _client({
        ingest.HOUSE_URL.format(week=dt.date(2026, 11, 9)): httpx.Response(200, content=week),
        ingest.SENATE_DAYS_URL: httpx.Response(200, content=SESSION_DAYS),
        ingest.SENATE_DAY_URL.format(day=dt.date(2026, 11, 11)):
            httpx.Response(200, content=b"<daily_senate_floor_activity><date>"),
    })

    ingest.ingest(client, dt.date(2026, 11, 12))

    assert not (tmp_path / "house").exists() or not list((tmp_path / "house").iterdir())
    assert sorted(p.name for p in (tmp_path / "senate").iterdir()) == ["session_days.xml"]
    assert "not from the 119th Congress" in caplog.text
    assert "senate floor schedule not updated" in caplog.text


def test_senate_files_from_another_congress_are_not_saved(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path / "house")
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path / "senate")
    client = _client({ingest.SENATE_DAYS_URL: httpx.Response(200, content=SESSION_DAYS.replace(b'"119"', b'"120"'))})

    ingest.ingest(client, dt.date(2026, 11, 12))

    assert not (tmp_path / "senate" / "session_days.xml").exists()
    assert "Senate session days are not from the 119th Congress" in caplog.text


def test_a_failed_fetch_logs_and_keeps_the_last_good_files(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path / "house")
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path / "senate")
    (tmp_path / "senate").mkdir()
    (tmp_path / "senate" / "session_days.xml").write_bytes(SESSION_DAYS)
    client = Client(delay=0, transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    monkeypatch.setattr("yan.http.RETRY_BACKOFF_SECONDS", [])

    ingest.ingest(client, dt.date(2026, 11, 12))  # doesn't raise

    assert (tmp_path / "senate" / "session_days.xml").read_bytes() == SESSION_DAYS
    assert "house floor schedule for week of 2026-11-09 not updated" in caplog.text
    assert "house floor schedule for week of 2026-11-16 not updated" in caplog.text
    assert "senate floor schedule not updated" in caplog.text
