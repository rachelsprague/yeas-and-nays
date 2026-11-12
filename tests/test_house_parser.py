from pathlib import Path

from yan.ingest.house import is_vote
from yan.stage.house import parse_vote

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_yea_and_nay_vote():
    vote, positions = parse_vote((FIXTURES / "house_2025_roll010.xml").read_bytes(), "2025/roll010.xml")

    assert vote["congress"] == "119"
    assert vote["session"] == "1st"
    assert vote["rollcall_num"] == "10"
    assert vote["legis_num"] == "H R 153"
    assert vote["vote_question"] == "On Motion to Suspend the Rules and Pass"
    assert vote["vote_result"] == "Passed"
    assert vote["action_date"] == "14-Jan-2025"
    assert vote["action_time_etz"] == "14:28"
    assert (vote["yea_total"], vote["nay_total"], vote["not_voting_total"]) == ("426", "0", "8")

    assert len(positions) == 434
    first = positions[0]
    assert first["bioguide_id"] == "A000370"
    assert (first["party"], first["state"], first["vote"]) == ("D", "NC", "Yea")
    assert sum(p["vote"] == "Yea" for p in positions) == 426


def test_speaker_election_has_candidate_positions_and_no_yea_nay_totals():
    vote, positions = parse_vote(
        (FIXTURES / "house_2025_roll002_speaker.xml").read_bytes(), "2025/roll002.xml"
    )

    assert vote["vote_question"] == "Election of the Speaker"
    assert vote["vote_result"] == "Johnson (LA)"
    assert vote["legis_num"] is None
    assert vote["yea_total"] is None
    assert {p["vote"] for p in positions} == {"Johnson (LA)", "Jeffries", "Emmer"}


def test_past_the_last_roll_call_is_not_a_vote():
    # The Clerk answers 200 with this body for roll numbers that don't exist yet.
    assert not is_vote(b'<xml>Error sanitizing file "roll999.xml". Please try again.</xml>')
    assert is_vote((FIXTURES / "house_2025_roll010.xml").read_bytes())
