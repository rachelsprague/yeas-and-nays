import json

import pytest

from yan.stage.legislators import parse, parse_dir, parse_social, parse_social_dir

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
         "social": {"twitter": "SenExample", "twitter_id": 123, "youtube_id": "UCabc", "mastodon": "@ex@example.social",
                    "bluesky": "example.senate.gov"}},
        {"id": {"govtrack": 2}, "social": {"twitter": "NoBioguide"}},
    ])

    assert rows == [{
        "bioguide_id": "X000001", "twitter": "SenExample", "facebook": None, "instagram": None,
        "youtube": None, "youtube_id": "UCabc", "mastodon": "@ex@example.social",
        "bluesky": "example.senate.gov",
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


@pytest.mark.parametrize("item", [None, "X000002", ["X000002"]], ids=["null", "string", "list"])
def test_skips_a_list_item_that_is_not_an_object(item, caplog):
    people, terms, _ = parse([PEOPLE[0], item], is_current=True)
    assert [p["bioguide_id"] for p in people] == ["X000001"]
    assert [t["bioguide_id"] for t in terms] == ["X000001"]
    rows = parse_social([item, {"id": {"bioguide": "X000001"}, "social": {}}])
    assert [r["bioguide_id"] for r in rows] == ["X000001"]
    assert caplog.text.count(f"isn't an object ({item!r})") == 2


@pytest.mark.parametrize("name", [None, "Pat Example", ["Pat"]], ids=["null", "string", "list"])
def test_a_name_that_is_not_an_object_reads_as_empty(name, caplog):
    entries = [{"id": {"bioguide": "X000003"}, "name": name, "terms": []},
               {"id": {"govtrack": 3}, "name": name, "terms": []}]

    people, _, _ = parse(entries, is_current=True)
    assert [(p["bioguide_id"], p["last_name"], p["official_full_name"]) for p in people] == [
        ("X000003", None, None)]
    assert "no bioguide ID (None)" in caplog.text


@pytest.mark.parametrize("value", [None, "x", 1], ids=["null", "string", "int"])
def test_null_or_wrong_type_nested_fields_read_as_empty(value):
    people, terms, affiliations = parse([
        {"id": {"bioguide": "X000003"}, "name": {"last": "No Terms"}, "terms": value},
        {"id": {"bioguide": "X000004"}, "name": {"last": "No Affiliations"},
         "terms": [{"type": "rep", "start": "2025-01-03", "party_affiliations": value}]},
    ], is_current=True)
    assert [p["bioguide_id"] for p in people] == ["X000003", "X000004"]
    assert [t["bioguide_id"] for t in terms] == ["X000004"]
    assert affiliations == []

    rows = parse_social([{"id": {"bioguide": "X000003"}, "social": value}])
    assert rows == [{"bioguide_id": "X000003"} | {f: None for f in
                    ("twitter", "facebook", "instagram", "youtube", "youtube_id", "mastodon", "bluesky")}]


def test_skips_a_term_or_affiliation_that_is_not_an_object(caplog):
    _, terms, affiliations = parse([
        {"id": {"bioguide": "X000003"}, "name": {"last": "Odd Terms"},
         "terms": [None, {"type": "rep", "start": "2025-01-03",
                          "party_affiliations": ["Republican", {"start": "2025-01-03", "party": "Independent"}]}]},
    ], is_current=True)
    assert [t["term_type"] for t in terms] == ["rep"]
    assert [a["party"] for a in affiliations] == ["Independent"]
    assert caplog.text.count("isn't an object") == 2


def test_malformed_id_warning_names_the_member(caplog):
    parse([{"id": {"bioguide": "x000001"}, "name": {"last": "Malformed", "official_full": "Pat Malformed"}}],
          is_current=True)
    assert "malformed bioguide ID 'x000001' ('Pat Malformed')" in caplog.text


def test_logged_labels_are_capped(caplog):
    parse_social([{"id": {"bioguide": "X" * 500, "govtrack": 1}, "social": {}}])
    parse([{"id": {}, "name": {"last": "L" * 500}}, ["Y" * 500]], is_current=True)

    assert len(caplog.records) == 3
    assert caplog.text.count("…") == 4
    assert not any(c * 80 in caplog.text for c in "XLY")


@pytest.mark.parametrize("filename, parse_file", [
    ("legislators-current.json", parse_dir),
    ("legislators-historical.json", parse_dir),
    ("legislators-social-media.json", parse_social_dir),
])
def test_a_file_whose_top_level_is_not_a_list_fails(filename, parse_file, tmp_path):
    for name in ("legislators-current.json", "legislators-historical.json", "legislators-social-media.json"):
        (tmp_path / name).write_text("[]")
    (tmp_path / filename).write_text(json.dumps({"X000001": {"id": {"bioguide": "X000001"}}}))
    with pytest.raises(ValueError, match=f"{filename} top level is dict, not a list"):
        parse_file(tmp_path)


def test_field_values_of_the_wrong_type_stage_as_null(caplog):
    people, terms, affiliations = parse([
        {"id": {"bioguide": "X000005", "lis": 999},
         "name": {"first": ["Pat"], "last": "Example", "official_full": {"x": 1}},
         "terms": [{"type": "rep", "start": "2025-01-03", "state": 6, "district": "3", "party": True,
                    "party_affiliations": [{"start": "2025-01-03", "party": ["Independent"]}]}]},
        {"id": {"bioguide": "X000006"}, "name": {"last": "Sample"},
         "terms": [{"type": "rep", "start": "2025-01-03", "district": True}]},
    ], is_current=True)
    assert people[0] == {
        "bioguide_id": "X000005", "lis_id": "999", "first_name": None, "last_name": "Example",
        "official_full_name": None, "is_current": True,
    }
    assert [(t["state"], t["district"], t["party"]) for t in terms] == [("6", None, None), (None, None, None)]
    assert affiliations[0]["party"] is None
    assert caplog.text.count("of the wrong type") == 6
    assert "X000005 has a district of the wrong type, staged as null ('3')" in caplog.text

    rows = parse_social([{"id": {"bioguide": "X000005"}, "social": {"twitter": {"x": 1}, "youtube_id": 42}}])
    assert (rows[0]["twitter"], rows[0]["youtube_id"]) == (None, "42")


def test_a_wrong_type_term_start_is_logged_once(caplog):
    _, terms, affiliations = parse([
        {"id": {"bioguide": "X000007"}, "name": {"last": "Example"},
         "terms": [{"type": "rep", "start": {"x": 1}, "district": 1, "party_affiliations": [
             {"start": "2025-01-03", "party": "Republican"}, {"start": "2026-03-09", "party": "Independent"},
         ]}]},
    ], is_current=True)
    assert terms[0]["term_start"] is None
    assert [a["term_start"] for a in affiliations] == [None, None]
    assert caplog.text.count("of the wrong type") == 1
