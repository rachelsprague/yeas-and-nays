import datetime as dt
import json

from yan.export.json_export import dumps, meta_document, summary_document, vote_document, with_measure_label


def test_dumps_is_valid_sorted_and_one_list_item_per_line():
    text = dumps({"b": [{"y": 1, "x": dt.date(2025, 1, 3)}, {"y": 2}], "a": 1})
    assert json.loads(text) == {"a": 1, "b": [{"x": "2025-01-03", "y": 1}, {"y": 2}]}
    assert text.splitlines() == ["{", '  "a": 1,', '  "b": [', '    {"x":"2025-01-03","y":1},', '    {"y":2}', "  ]", "}"]


def test_vote_document_lists_only_members_against_majority():
    positions = [
        {"bioguide_id": "A1", "member_label": "A (R-TX-1)", "party": "R", "caucus_party": "R",
         "position_raw": "Yea", "position": "yes", "caucus_majority_position": "yes",
         "voted_against_party_majority": False},
        {"bioguide_id": "A2", "member_label": "B (R-TX-2)", "party": "R", "caucus_party": "R",
         "position_raw": "Nay", "position": "no", "caucus_majority_position": "yes",
         "voted_against_party_majority": True},
        {"bioguide_id": "A3", "member_label": "C (I-VT)", "party": "I", "caucus_party": "D",
         "position_raw": "Not Voting", "position": "not_voting", "caucus_majority_position": "no",
         "voted_against_party_majority": None},
    ]
    doc = vote_document({"vote_id": "h119-1-0001"}, positions)

    assert doc["against_party_majority"] == [{"bioguide_id": "A2", "member_label": "B (R-TX-2)", "position": "Nay"}]
    assert doc["party_totals"] == {"R": {"yes": 1, "no": 1}, "I": {"not_voting": 1}}
    assert doc["caucus_majority_position"] == {"R": "yes", "D": "no"}
    assert doc["positions"] == {"A1": "Yea", "A2": "Nay", "A3": "Not Voting"}
    assert doc["summary"] is None


def test_meta_tracks_latest_roll_per_chamber_and_session():
    votes = [
        {"chamber": "house", "session": 1, "roll_number": 362, "vote_date": dt.date(2025, 12, 18)},
        {"chamber": "house", "session": 2, "roll_number": 5, "vote_date": dt.date(2026, 1, 7)},
        {"chamber": "senate", "session": 1, "roll_number": 659, "vote_date": dt.date(2025, 12, 18)},
    ]
    meta = meta_document(votes, members=[{}, {}])
    assert meta["latest_roll_number"] == {"house": {"1": 362, "2": 5}, "senate": {"1": 659}}
    assert meta["latest_vote_date"] == dt.date(2026, 1, 7)
    assert meta["member_count"] == 2


def test_votes_carry_measure_number_in_citation_form():
    assert with_measure_label({"chamber": "house", "measure_number": "H RES 1655"})["measure_label"] == "H.Res. 1655"
    assert with_measure_label({"chamber": "senate", "measure_number": "PN1129"})["measure_label"] == "PN1129"
    assert with_measure_label({"chamber": "house", "measure_number": None})["measure_label"] is None


def test_summary_carries_the_version_it_describes():
    summary = {"summary_html": "<p>This bill&nbsp;allows X.</p>", "action_desc": "Introduced in House",
               "action_date": dt.date(2025, 2, 5), "version_code": "00"}
    assert summary_document(summary) == {
        "html": "<p>This bill allows X.</p>", "version": "Introduced in House",
        "version_date": dt.date(2025, 2, 5), "version_code": "00",
    }
    assert summary_document(None) is None
