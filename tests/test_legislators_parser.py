from yan.stage.legislators import parse

PEOPLE = [
    {
        "id": {"bioguide": "X000001", "lis": "S999"},
        "name": {"first": "Pat", "last": "Example", "official_full": "Pat Example"},
        "terms": [
            {"type": "sen", "start": "2025-01-03", "end": "2031-01-03", "state": "VT",
             "party": "Independent", "caucus": "Democrat"},
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

    assert [(a["bioguide_id"], a["party"], a["caucus"]) for a in affiliations] == [
        ("X000002", "Republican", None),
        ("X000002", "Independent", "Republican"),
    ]
    assert all(a["term_start"] == "2025-01-03" for a in affiliations)
