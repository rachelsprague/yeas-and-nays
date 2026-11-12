from pathlib import Path

from yan.ingest.senate import vote_numbers_from_menu
from yan.stage.senate import parse_vote

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_vote_metadata_and_members():
    vote, positions = parse_vote((FIXTURES / "senate_119_1_00001.xml").read_bytes(), "119/1/vote_119_1_00001.xml")

    assert (vote["congress"], vote["session"], vote["vote_number"]) == ("119", "1", "1")
    # Whitespace in the official date is collapsed so dbt can parse it.
    assert vote["vote_date"] == "January 9, 2025, 02:54 PM"
    assert vote["vote_question_text"] == "On Cloture on the Motion to Proceed S. 5"
    assert vote["vote_result"] == "Cloture on the Motion to Proceed Agreed to"
    assert vote["document_name"] == "S. 5"
    assert (vote["yeas"], vote["nays"], vote["present"], vote["absent"]) == ("84", "9", None, "6")
    assert vote["tie_breaker_by_whom"] is None

    assert len(positions) == 99
    first = positions[0]
    assert (first["lis_member_id"], first["last_name"], first["party"], first["state"], first["vote_cast"]) == (
        "S428", "Alsobrooks", "D", "MD", "Yea",
    )


def test_vote_menu_lists_vote_numbers_in_order():
    menu = b"""<vote_summary><votes>
        <vote><vote_number>00003</vote_number></vote>
        <vote><vote_number>00001</vote_number></vote>
        <vote><vote_number>00002</vote_number></vote>
    </votes></vote_summary>"""
    assert vote_numbers_from_menu(menu) == [1, 2, 3]


def test_vice_president_tie_break_is_captured_on_the_vote_not_as_a_position():
    vote, positions = parse_vote(
        (FIXTURES / "senate_119_1_00015_tie_break.xml").read_bytes(), "119/1/vote_119_1_00015.xml"
    )

    assert (vote["yeas"], vote["nays"]) == ("50", "50")
    assert vote["tie_breaker_by_whom"] == "Vice President of the United States"
    assert vote["tie_breaker_vote"] == "Yea"
    assert len(positions) == 100
