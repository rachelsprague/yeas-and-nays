import datetime as dt
import json

import httpx
import pytest

from yan.ingest import directory as ingest
from yan.stage import directory

# Laid out like the GovInfo text of the Congressional Directory (names invented), with
# CRLF line ends, the variants the 2026 edition has, and a biography outside any state.
TEXT = """\
                           THE VICE PRESIDENT

    ALEX SAMPLE, Republican, of Town, OH; born in Town, OH, May 1, 1980;
education: B.A., Example College, 2002; election history: elected Vice
President on November 5, 2024.
<DOC>
.
                                 ALABAMA

----------------------------------------------------------------------
 SENATORS                                                           REPRESENTATIVES
----------------------------------------------------------------------
   Pat Example                             1. Chris McEXAMPLE
----------------------------------------------------------------------


 SENATORS

PAT EXAMPLE, Jr., Republican, of Auburn, AL; born in Camden, AR,
September 18, 1954; education: B.S., physical education, Southern
Arkansas University, 1976; professional history: football coach, 1976-
79; military service: U.S. Army, 1972-74; election history: elected to
the U.S. Senate on November 3, 2020.

                          Congressional Office
455 Russell Senate Office Building, Washington, DC        (202) 224-4124

*  *  *

 FIRST DISTRICT

CHRIS McEXAMPLE, Democratic-Farmer-Labor Party, of Mobile, AL; born in
Mobile, AL, education: B.A., Example University; professional history:
teacher; election history: elected to the 119th Congress.

 TWENTY-THIRD DISTRICT

SAM KAMLAGER-
DOVE, Republican of Dothan, AL; raised in Dothan, AL; education: B.A.,
State College; professional history: lawyer; election history: elected
to the 118th Congress.
<DOC>
.
                          DISTRICT OF COLUMBIA

DELEGATE

AT LARGE

JO EXAMPLE, Democrat Delegate, of Washington, DC; born in Washington, DC;
education: J.D., Example Law School; professional history: professor;
election history: elected to the 102nd Congress.
<DOC>
.
                          STANDING COMMITTEES OF THE HOUSE

PAT EXAMPLE, Jr., Republican, of Auburn, AL; listed here again, outside a state.
""".replace("\n", "\r\n")


def test_parse_reads_each_seat_and_field():
    rows = directory.parse(TEXT)
    assert [(r["state"], r["chamber"], r["district"], r["printed_name"]) for r in rows] == [
        ("AL", "senate", None, "PAT EXAMPLE, Jr."),
        ("AL", "house", 1, "CHRIS McEXAMPLE"),
        ("AL", "house", 23, "SAM KAMLAGER-DOVE"),
        ("DC", "house", 0, "JO EXAMPLE"),
    ]
    senator = rows[0]
    assert senator["opening"] == "of Auburn, AL; born in Camden, AR, September 18, 1954"
    assert senator["education"] == "B.S., physical education, Southern Arkansas University, 1976"
    # A line ending in a hyphen continues without a space.
    assert senator["professional_history"] == "football coach, 1976-79"
    assert senator["military_service"] == "U.S. Army, 1972-74"
    assert senator["election_history"] == "elected to the U.S. Senate on November 3, 2020"


def test_parse_takes_openings_as_printed():
    rows = {r["printed_name"]: r for r in directory.parse(TEXT)}
    # A label after a comma still ends the opening.
    assert rows["CHRIS McEXAMPLE"]["opening"] == "of Mobile, AL; born in Mobile, AL"
    assert rows["CHRIS McEXAMPLE"]["education"] == "B.A., Example University"
    assert rows["SAM KAMLAGER-DOVE"]["opening"] == "of Dothan, AL; raised in Dothan, AL"
    assert rows["SAM KAMLAGER-DOVE"]["military_service"] is None
    assert rows["JO EXAMPLE"]["opening"] == "of Washington, DC; born in Washington, DC"


def test_district_ordinals():
    assert directory.ORDINALS["FIRST"] == 1
    assert directory.ORDINALS["NINETEENTH"] == directory.ORDINALS["NINTEENTH"] == 19
    assert directory.ORDINALS["TWENTIETH"] == 20
    assert directory.ORDINALS["FIFTY-SECOND"] == 52


def test_parse_dir_reads_the_newest_edition(tmp_path):
    assert directory.parse_dir(tmp_path) == []
    (tmp_path / "CDIR-2024-04-25.txt").write_text("")
    (tmp_path / "CDIR-2026-02-20.txt").write_text(TEXT)
    rows = directory.parse_dir(tmp_path)
    assert len(rows) == 4
    assert {(r["source_file"], r["edition"], r["date_issued"]) for r in rows} == {
        ("CDIR-2026-02-20.txt", "CDIR-2026-02-20", "2026-02-20")
    }


def test_newest_edition_skips_ids_not_in_the_expected_form():
    assert ingest.newest_edition([
        {"packageId": "CDIR-2024-04-25", "dateIssued": "2024-04-25"},
        {"packageId": "CDIR-2026-02-20", "dateIssued": "2026-02-20"},
        {"packageId": "../CDIR-2027", "dateIssued": "2027-01-01"},
        {"packageId": "CDIR-2027-01-01", "dateIssued": None},
        "not a package",
    ]) == "CDIR-2026-02-20"
    assert ingest.newest_edition([]) is None


class _Client:
    def __init__(self, text):
        self.text, self.urls = text, []

    def get(self, url, headers=None):
        self.urls.append(url)
        request = httpx.Request("GET", url)
        if "/published/" in url:
            return httpx.Response(200, json={"packages": [{"packageId": "CDIR-2026-02-20", "dateIssued": "2026-02-20"}]},
                                  request=request)
        return httpx.Response(200, text=self.text, request=request)


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "DIR", tmp_path)
    monkeypatch.setattr(ingest, "MIN_BIOS", 4)
    monkeypatch.setenv("CONGRESS_API_KEY", "test-key")
    return tmp_path


def test_ingest_saves_the_newest_edition_and_drops_older_ones(raw):
    (raw / "CDIR-2024-04-25.txt").write_text("old")
    client = _Client(TEXT)
    ingest.ingest(client, today=dt.date(2026, 11, 18))
    assert sorted(p.name for p in raw.iterdir()) == ["CDIR-2026-02-20.txt", "editions.json"]
    assert client.urls[0].endswith("/published/2023-11-19?collection=CDIR&offsetMark=*&pageSize=100")
    # Checked again only once the saved list is a week old.
    ingest.ingest(client, today=dt.date(2026, 11, 18))
    assert len(client.urls) == 2


def test_ingest_keeps_the_saved_edition_when_a_new_one_parses_short(raw, caplog):
    (raw / "CDIR-2024-04-25.txt").write_text("old")
    ingest.ingest(_Client("not a directory"), today=dt.date(2026, 11, 18))
    assert sorted(p.name for p in raw.iterdir()) == ["CDIR-2024-04-25.txt"]
    assert "CDIR-2026-02-20 has 0 biographies" in caplog.text


def test_ingest_skips_without_a_key(raw, monkeypatch):
    monkeypatch.delenv("CONGRESS_API_KEY")
    client = _Client(TEXT)
    ingest.ingest(client)
    assert client.urls == []


def test_ingest_sends_the_key_only_in_a_header(raw):
    seen = []

    class Client(_Client):
        def get(self, url, headers=None):
            seen.append((url, headers))
            return super().get(url, headers)

    ingest.ingest(Client(TEXT), today=dt.date(2026, 11, 18))
    assert all(h == {"X-Api-Key": "test-key"} and "test-key" not in u for u, h in seen)
    assert json.loads((raw / "editions.json").read_text())[0]["packageId"] == "CDIR-2026-02-20"
