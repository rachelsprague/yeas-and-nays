import datetime as dt
from pathlib import Path

import httpx
import pytest

from yan.http import Client
from yan.ingest import floor as ingest
from yan.stage.floor import parse_house_day, parse_house_week, parse_senate_day, parse_session_days

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE_DAY = (FIXTURES / "house_floor_day_2026-11-13.xml").read_bytes()


@pytest.fixture(autouse=True)
def house_days_dir(monkeypatch, tmp_path):
    """Every test's House floor days go to a temporary folder, never data/raw."""
    path = tmp_path / "house_days"
    monkeypatch.setattr(ingest, "house_days_dir", lambda: path)
    return path


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


def test_malformed_values_stage_as_text_for_dbt_to_cast():
    # Bad or missing values are passed on as they are (or null); try_cast in
    # staging nulls them and the floor tests warn, so nothing here raises.
    house = b"""<floorschedule congress-num="next" week-date="Nov. 16">
      <category sort-order="second"><floor-items>
        <floor-item sort-order="" add-date="soon"><legis-num> </legis-num></floor-item>
      </floor-items></category></floorschedule>"""
    [row] = parse_house_week(house, "house/2026-11-16.xml")
    assert (row["congress"], row["week_date"], row["category_order"], row["add_date"]) == (
        "next", "Nov. 16", "second", "soon",
    )
    assert (row["category"], row["item_id"], row["legis_num"], row["floor_text"]) == (None,) * 4
    assert row["item_order"] == ""  # try_cast('' as integer) is null

    senate = b"""<daily_senate_floor_activity><date_iso_8601>11/12</date_iso_8601>
      <document><amendment_docnum>Amendment to H.R. 2347</amendment_docnum>
        <amendment_status_text>Cloture motion presented in Senate.</amendment_status_text></document>
    </daily_senate_floor_activity>"""
    [row] = parse_senate_day(senate, "senate/2026-11-12.xml")
    assert (row["activity_date"], row["docnum"], row["document_title"]) == ("11/12", None, None)

    days = b"""<CongressSessionDayConvenings><LegislativeDay><SessionDay>
      <ConveneDate>noon</ConveneDate></SessionDay></LegislativeDay></CongressSessionDayConvenings>"""
    [row] = parse_session_days(days, "senate/session_days.xml")
    assert (row["legislative_day"], row["convene_time"], row["next_convene_time"]) == (None, "noon", None)


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


def test_senate_title_joins_only_marks_that_end_a_word():
    senate = b"""<daily_senate_floor_activity><date_iso_8601>2026-11-12</date_iso_8601>
      <document><docnum>S. 1</docnum><document_title>A bill on .NET use , to cut costs by
        .5 percent , and for other purposes
        .</document_title>
        <document_status_text>Read twice.</document_status_text></document>
    </daily_senate_floor_activity>"""
    [row] = parse_senate_day(senate, "senate/2026-11-12.xml")
    assert row["document_title"] == "A bill on .NET use, to cut costs by .5 percent, and for other purposes."


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


def test_session_days_keep_the_pro_forma_flag_as_recorded():
    days = b"""<CongressSessionDayConvenings><LegislativeDay><SessionDay>
      <NextConveneDate>2026-11-17T10:00:00-05:00</NextConveneDate><IsNextConveneProforma>Y</IsNextConveneProforma>
      </SessionDay><SessionDay><IsNextConveneProforma>
      </IsNextConveneProforma></SessionDay></LegislativeDay></CongressSessionDayConvenings>"""
    assert [r["next_convene_pro_forma"] for r in parse_session_days(days, "senate/session_days.xml")] == ["Y", None]


def test_house_day_gives_the_convening_and_once_finished_the_next():
    row = parse_house_day(HOUSE_DAY, "house_days/2026-11-13.xml")
    assert row == {
        "source_file": "house_days/2026-11-13.xml", "legislative_day": "20261113",
        "convene_time": "20261113T10:00:00", "finished": "Yes", "next_convene_time": "20261117T12:00",
    }


def test_house_day_in_progress_has_no_next_convening():
    content = HOUSE_DAY.replace(
        b'<legislative_day_finished next-legislative-day-convenes="20261117T12:00">Yes</legislative_day_finished>\n', b""
    )
    row = parse_house_day(content, "house_days/2026-11-13.xml")
    assert (row["convene_time"], row["finished"], row["next_convene_time"]) == ("20261113T10:00:00", None, None)


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
        ingest.HOUSE_URL.format(week=dt.date(2026, 11, 16)):
            httpx.Response(200, content=week.replace(b'week-date="2026-11-09"', b'week-date="2026-11-16"')),
    })

    ingest.ingest_house(client, dt.date(2026, 11, 12))

    assert [p.name for p in tmp_path.iterdir()] == ["2026-11-16.xml"]
    assert "house floor schedule for week of 2026-11-09 not updated" in caplog.text


def test_a_house_file_for_another_week_is_not_saved(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "house_dir", lambda: tmp_path)
    (tmp_path / "2026-11-16.xml").write_text("last good copy")
    week = (FIXTURES / "house_floor_2026-11-09.xml").read_bytes()
    client = _client({ingest.HOUSE_URL.format(week=dt.date(2026, 11, 16)): httpx.Response(200, content=week)})

    ingest.ingest_house(client, dt.date(2026, 11, 12))

    assert (tmp_path / "2026-11-16.xml").read_text() == "last good copy"
    assert "House floor schedule for week of 2026-11-16 has week-date '2026-11-09'" in caplog.text


def _session_days(*sessions: tuple[str, str]) -> bytes:
    return b'<CongressSessionDayConvenings Congress="119">' + "".join(
        f"<LegislativeDay><SessionDay><ConveneDate>{convene}</ConveneDate><AdjournDate>{adjourn}</AdjournDate>"
        "</SessionDay></LegislativeDay>"
        for convene, adjourn in sessions
    ).encode() + b"</CongressSessionDayConvenings>"


def _session(day: dt.date, minutes: int) -> tuple[str, str]:
    start = dt.datetime.combine(day, dt.time(12), dt.timezone(dt.timedelta(hours=-5)))
    return start.isoformat(), (start + dt.timedelta(minutes=minutes)).isoformat()


def test_brief_senate_days_dont_use_up_the_window():
    full = [dt.date(2026, 9, d) for d in range(17, 29)]
    brief = [dt.date(2026, 10, d) for d in range(1, 13)]
    content = _session_days(*(_session(d, 300) for d in full), *(_session(d, 1) for d in brief))

    # The ten latest full days, and every brief day since.
    assert ingest.recent_days(content, dt.date(2026, 10, 12)) == full[-10:] + brief
    # Days after today don't count.
    assert ingest.recent_days(content, full[-1]) == full[-10:]


def test_with_only_brief_senate_days_the_latest_ten_are_read():
    brief = [dt.date(2026, 10, d) for d in range(1, 13)]
    assert ingest.recent_days(_session_days(*(_session(d, 1) for d in brief)), brief[-1]) == brief[-10:]


def test_a_senate_day_is_brief_only_if_each_session_is_known_to_be():
    content = _session_days(
        _session(dt.date(2026, 10, 1), 5), _session(dt.date(2026, 10, 2), 6),
        ("2026-10-05T12:00:00-04:00", ""), ("2026-10-06T12:00:00-04:00", "noon"),
        _session(dt.date(2026, 10, 7), 1), _session(dt.date(2026, 10, 7), 60),
        _session(dt.date(2026, 10, 8), -60),
    )
    assert ingest.brief_days(content) == {dt.date(2026, 10, 1)}


def test_a_bad_senate_day_still_fetches_the_newer_days(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path)
    day = (FIXTURES / "senate_floor_2026-11-11.xml").read_bytes()
    client = _client({
        ingest.SENATE_DAYS_URL: httpx.Response(200, content=SESSION_DAYS),
        ingest.SENATE_DAY_URL.format(day=dt.date(2026, 11, 11)):
            httpx.Response(200, content=b"<daily_senate_floor_activity><congress>"),
        ingest.SENATE_DAY_URL.format(day=dt.date(2026, 11, 12)):
            httpx.Response(200, content=day.replace(b"2026-11-11", b"2026-11-12")),
    })

    ingest.ingest_senate(client, dt.date(2026, 11, 12))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-12.xml", "session_days.xml"]
    assert "senate floor activity for 2026-11-11 not updated" in caplog.text


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


def test_ingest_senate_refetches_only_the_two_newest_days(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "senate_dir", lambda: tmp_path)
    days = [dt.date(2026, 11, d) for d in (9, 10, 11, 12, 13)]
    session_days = b'<CongressSessionDayConvenings Congress="119">' + b"".join(
        f"<LegislativeDay><SessionDay><ConveneDate>{d}T12:00:00-05:00</ConveneDate></SessionDay>"
        "</LegislativeDay>".encode()
        for d in days
    ) + b"</CongressSessionDayConvenings>"
    # Nov. 9 and 11 were saved by an earlier run; Nov. 10 is missing.
    for day in ("2026-11-09", "2026-11-11"):
        (tmp_path / f"{day}.xml").write_text("earlier copy")
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        if str(request.url) == ingest.SENATE_DAYS_URL:
            return httpx.Response(200, content=session_days)
        return httpx.Response(200, content=b"<daily_senate_floor_activity><congress>119</congress>"
                                           b"</daily_senate_floor_activity>")

    ingest.ingest_senate(Client(delay=0, transport=httpx.MockTransport(handler)), dt.date(2026, 11, 12))

    # Nov. 13 is after today; Nov. 11 and 12 are the two newest, refetched even if saved.
    assert fetched[1:] == [ingest.SENATE_DAY_URL.format(day=dt.date(2026, 11, d)) for d in (10, 11, 12)]
    assert (tmp_path / "2026-11-09.xml").read_text() == "earlier copy"
    assert (tmp_path / "2026-11-11.xml").read_text() != "earlier copy"


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
    assert "senate floor activity for 2026-11-11 not updated" in caplog.text


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


def test_house_days_keep_only_the_newest_file(house_days_dir):
    house_days_dir.mkdir()
    (house_days_dir / "2026-11-12.xml").write_text("older day")
    client = _client({
        ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, 13)): httpx.Response(200, content=HOUSE_DAY),
        ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, 14)): httpx.Response(404, text="<html>Not Found</html>"),
    })

    ingest.ingest_house_days(client, dt.date(2026, 11, 14))

    assert [p.name for p in house_days_dir.iterdir()] == ["2026-11-13.xml"]
    assert (house_days_dir / "2026-11-13.xml").read_bytes() == HOUSE_DAY


def test_house_days_keep_the_last_file_through_a_recess(house_days_dir, caplog):
    house_days_dir.mkdir()
    (house_days_dir / "2026-11-13.xml").write_bytes(HOUSE_DAY)
    client = _client({})  # Nothing posted for Nov. 19 or 20.

    with caplog.at_level("INFO"):
        ingest.ingest_house_days(client, dt.date(2026, 11, 20))

    assert [p.name for p in house_days_dir.iterdir()] == ["2026-11-13.xml"]
    assert "house floor proceedings for 2026-11-20: not published" in caplog.text


def test_house_day_from_another_congress_is_not_saved(house_days_dir, caplog):
    client = _client({
        ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, 13)):
            httpx.Response(200, content=HOUSE_DAY.replace(b'congress="119"', b'congress="120"')),
    })

    ingest.ingest_house_days(client, dt.date(2026, 11, 13))

    assert not house_days_dir.exists() or not list(house_days_dir.iterdir())
    assert "House floor proceedings for 2026-11-13 are not from the 119th Congress" in caplog.text


def test_with_nothing_saved_house_days_look_back_for_the_last_day_met(house_days_dir):
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        if str(request.url) == ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, 13)):
            return httpx.Response(200, content=HOUSE_DAY)
        return httpx.Response(404, text="<html>Not Found</html>")

    ingest.ingest_house_days(Client(delay=0, transport=httpx.MockTransport(handler)), dt.date(2026, 11, 16))

    # Nov. 15 and 16 first, then back from Nov. 14 until a day is found.
    assert fetched == [ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, d)) for d in (15, 16, 14, 13)]
    assert [p.name for p in house_days_dir.iterdir()] == ["2026-11-13.xml"]


def test_house_days_look_back_at_most_two_weeks(house_days_dir):
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        return httpx.Response(404, text="<html>Not Found</html>")

    ingest.ingest_house_days(Client(delay=0, transport=httpx.MockTransport(handler)), dt.date(2026, 11, 16))

    assert len(fetched) == ingest.HOUSE_LOOKBACK_DAYS + 1  # yesterday and today, then Nov. 14 back to Nov. 2
    assert fetched[-1] == ingest.HOUSE_DAY_URL.format(day=dt.date(2026, 11, 2))
