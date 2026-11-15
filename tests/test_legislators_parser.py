import json

import pytest

from yan.stage.legislators import parse, parse_social, parse_social_dir

PEOPLE = [
    {
        "id": {"bioguide": "X000001", "lis": "S999"},
        "name": {"first": "Pat", "last": "Example", "official_full": "Pat Example"},
        "terms": [
            {"type": "sen", "start": "2025-01-03", "end": "2031-01-03", "state": "VT",
             "party": "Independent", "caucus": "Democrat", "url": "https://www.example.senate.gov",
             "contact_form": "https://www.example.senate.gov/contact", "phone": "202-224-0000",
             "office": "1 Example Senate Office Building", "rss_url": "https://www.example.senate.gov/rss"},
        ],
    },
    {
        "id": {"bioguide": "X000002"},
        "name": {"first": "Sam", "last": "Sample"},
        "terms": [
            {"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "CA", "district": 3,
             "party": "Independent", "caucus": "Republican",
             "party_affiliations": [
                 {"start": "2025-01-03", "end": "2026-03-08", "party": "Republican"},
                 {"start": "2026-03-09", "end": "2027-01-03", "party": "Independent", "caucus": "Republican"},
             ]},
        ],
    },
    {"id": {"govtrack": 1}, "name": {"last": "No Bioguide"}, "terms": []},
]


def test_flattens_people_terms_and_affiliations():
    people, terms, affiliations = parse(PEOPLE, is_current=True)

    assert [p["bioguide_id"] for p in people] == ["X000001", "X000002"]
    assert people[0]["lis_id"] == "S999"
    assert people[1]["lis_id"] is None
    assert all(p["is_current"] for p in people)

    assert terms[0]["caucus"] == "Democrat"
    assert terms[1]["district"] == 3
    assert {k: terms[0][k] for k in ("url", "contact_form", "phone", "office")} == {
        "url": "https://www.example.senate.gov", "contact_form": "https://www.example.senate.gov/contact",
        "phone": "202-224-0000", "office": "1 Example Senate Office Building",
    }
    assert terms[1]["contact_form"] is None

    assert [(a["bioguide_id"], a["party"], a["caucus"]) for a in affiliations] == [
        ("X000002", "Republican", None),
        ("X000002", "Independent", "Republican"),
    ]
    assert all(a["term_start"] == "2025-01-03" for a in affiliations)


def test_social_keeps_account_names_as_recorded():
    rows = parse_social([
        {"id": {"bioguide": "X000001", "govtrack": 1},
         "social": {"twitter": "SenExample", "twitter_id": 123, "youtube_id": "UCabc", "mastodon": "@ex@example.social"}},
        {"id": {"govtrack": 2}, "social": {"twitter": "NoBioguide"}},
    ])

    assert rows == [{
        "bioguide_id": "X000001", "twitter": "SenExample", "facebook": None, "instagram": None,
        "youtube": None, "youtube_id": "UCabc", "mastodon": "@ex@example.social",
    }]


@pytest.mark.parametrize("bioguide", ["x000001", "X00001", "X0000001", "X000001\n", "../X000001", 1234567])
def test_skips_a_malformed_bioguide_id(bioguide, caplog):
    entry = {"id": {"bioguide": bioguide}, "name": {"last": "Malformed"},
             "terms": [{"type": "rep", "start": "2025-01-03",
                        "party_affiliations": [{"start": "2025-01-03", "party": "Independent"}]}]}

    people, terms, affiliations = parse([PEOPLE[0], entry], is_current=True)
    assert [p["bioguide_id"] for p in people] == ["X000001"]
    assert [t["bioguide_id"] for t in terms] == ["X000001"]
    assert affiliations == []
    assert parse_social([{"id": {"bioguide": bioguide}, "social": {"twitter": "Malformed"}}]) == []
    assert caplog.text.count("malformed bioguide ID") == 2


@pytest.mark.parametrize("ids", [None, "B000001", ["B000001"]], ids=["null", "string", "list"])
def test_skips_an_entry_without_an_id_block(ids, caplog):
    entries = [{"name": {"last": "No ID"}, "terms": [{"type": "rep", "start": "2025-01-03"}]},
               {"id": ids, "name": {"last": "Bad ID"}, "terms": [{"type": "rep", "start": "2025-01-03"}]}]

    people, terms, _ = parse([PEOPLE[0], *entries], is_current=True)
    assert [p["bioguide_id"] for p in people] == ["X000001"]
    assert [t["bioguide_id"] for t in terms] == ["X000001"]
    assert parse_social([{"social": {"twitter": "NoId"}}, {"id": ids, "social": {}}]) == []
    assert caplog.text.count("no bioguide ID") == 4
    assert "'No ID'" in caplog.text and "'Bad ID'" in caplog.text
    assert f"no bioguide ID ({ids!r})" in caplog.text


def test_social_dir_without_the_file_stages_no_accounts(tmp_path):
    assert parse_social_dir(tmp_path) == []

    (tmp_path / "legislators-social-media.json").write_text(json.dumps(
        [{"id": {"bioguide": "X000001"}, "social": {"facebook": "example"}}]
    ))
    assert [r["facebook"] for r in parse_social_dir(tmp_path)] == ["example"]
