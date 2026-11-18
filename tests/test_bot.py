import json
from pathlib import Path

import pytest

from yan.bot import run as bot
from yan.bot import state as bot_state
from yan.bot.format import (PostTooLong, closing_marks, format_post, party_break_line, party_line, tally_line,
                            vote_page_url)
from yan.bot.rules import decide, measure_label
from yan.config import SITE_URL

FIXTURES = Path(__file__).parent / "fixtures"


def house_vote(**overrides):
    vote = {
        "vote_id": "h119-2-0317", "chamber": "house", "congress": 119, "session": 2, "roll_number": 317,
        "vote_date": "2026-11-10", "vote_time_et": "2026-11-10T15:00:00",
        "question": "On Motion to Refer", "result": "Passed", "measure_number": "H RES 1655",
        "measure_title": "Impeaching Peter Brian Hegseth, Secretary of Defense, for high crimes and misdemeanors",
        "vote_title": None, "amendment_number": None,
        "yea_count": 211, "nay_count": 204, "present_count": 0, "not_voting_count": 0,
        "tie_breaker_by": None, "tie_breaker_vote": None,
        "source_url": "https://clerk.house.gov/Votes/2026317",
    }
    return {**vote, **overrides}


def senate_vote(**overrides):
    vote = {
        "vote_id": "s119-1-0015", "chamber": "senate", "congress": 119, "session": 1, "roll_number": 15,
        "vote_date": "2025-01-24", "vote_time_et": "2025-01-24T21:00:00",
        "question": "On the Nomination PN11-7", "result": "Nomination Confirmed", "measure_number": "PN11-7",
        "measure_title": "Peter Hegseth, of Tennessee, to be Secretary of Defense",
        "vote_title": "On the Nomination: Peter Hegseth", "amendment_number": None,
        "yea_count": 50, "nay_count": 50, "present_count": 0, "not_voting_count": 0,
        "tie_breaker_by": "Vice President of the United States", "tie_breaker_vote": "Yea",
        "source_url": "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00015.htm",
    }
    return {**vote, **overrides}


def doc(vote, against=(), positions=None, party_totals=None):
    return {
        "vote": vote,
        "against_party_majority": [{"member_label": label} for label in against],
        "positions": positions or {"A000001": "Yea"},
        "party_totals": party_totals or {"R": {"yes": 1}, "D": {"no": 1}},
    }


# --- which votes get posted ----------------------------------------------

@pytest.mark.parametrize("vote, kind", [
    (house_vote(question="On Passage", measure_number="H R 153"), "passage"),
    (house_vote(question="On Agreeing to the Resolution", measure_number="H CON RES 14"), "passage"),
    (house_vote(question="On Motion to Suspend the Rules and Pass"), "passage"),
    (house_vote(question="Passage, Objections of the President To The Contrary Notwithstanding",
                measure_number="H R 1"), "veto_override"),
    (house_vote(), "disposing_motion"),
    (house_vote(question="On Motion to Table"), "disposing_motion"),
    (senate_vote(), "nomination"),
    (senate_vote(question="On the Cloture Motion PN373", result="Cloture Motion Agreed to"), "cloture"),
    (senate_vote(question="On Passage of the Bill H.R. 1", result="Bill Passed", measure_number="H.R. 1"),
     "passage"),
])
def test_posted(vote, kind):
    decision = decide(vote)
    assert decision.post and decision.kind == kind


@pytest.mark.parametrize("vote, reason", [
    (house_vote(question="On Agreeing to the Resolution", measure_title="Providing for consideration of the bill (H.R. 1)"),
     "rule"),
    (house_vote(question="On Motion to Recommit"), "procedural"),
    (house_vote(question="On Ordering the Previous Question"), "procedural"),
    (house_vote(question="On Agreeing to the Amendment"), "procedural"),
    (house_vote(question="On Motion to Adjourn"), "procedural"),
    (house_vote(question="On Motion to Suspend the Rules and Pass", result="Failed"), "did not pass"),
    (house_vote(question="On Agreeing to the Resolution", measure_number="H RES 189"), "simple resolution"),
    (house_vote(question="Election of the Speaker", result="Johnson (LA)", yea_count=None), "not a yea/nay"),
    # Disposing-motion exception applies only when the motion ends consideration.
    (house_vote(question="On Motion to Table", result="Failed"), "still pending"),
    (house_vote(question="On Motion to Table the Motion to Discharge Committee"), "procedural"),
    (senate_vote(question="On the Motion to Table S.J.Res. 49", result="Motion to Table Agreed to",
                 vote_title="Motion to Table the Motion to Reconsider the Vote by which S.J.Res. 49"),
     "amendment, motion"),
    (senate_vote(question="On the Motion to Table S.Amdt. 4236 to H.R. 7148", result="Motion to Table Agreed to",
                 amendment_number="S.Amdt. 4236", vote_title="Motion to Table Lee Amdt. No. 4236"),
     "amendment, motion"),
    (senate_vote(question="On the Resolution S.Res. 1", result="Resolution Agreed to", measure_number="S.Res. 1"),
     "procedural"),
])
def test_skipped(vote, reason):
    decision = decide(vote)
    assert not decision.post
    assert reason in decision.reason


def test_house_measure_numbers_use_citation_form():
    assert measure_label(house_vote(measure_number="H RES 1655")) == "H.Res. 1655"
    assert measure_label(house_vote(measure_number="H J RES 117")) == "H.J.Res. 117"
    assert measure_label(house_vote(measure_number="H R 153")) == "H.R. 153"
    assert measure_label(senate_vote(measure_number="S.J.Res. 49")) == "S.J.Res. 49"


# --- post formatting -----------------------------------------------------

def test_disposing_motion_post_matches_style_example():
    vote = house_vote(not_voting_count=18)
    totals = {"R": {"yes": 210, "no": 1, "not_voting": 7}, "D": {"no": 203, "not_voting": 11}, "I": {"yes": 1}}
    text = format_post(doc(vote, against=["Massie (R-KY-4)"], party_totals=totals), decide(vote))
    assert text == (
        'House agrees to motion to refer H.Res. 1655, "Impeaching Peter Brian Hegseth, '
        'Secretary of Defense, for high crimes and misdemeanors"\n'
        "211 Yea · 204 Nay · 18 Not Voting\n"
        "D 0–203 · I 1–0 · R 210–1\n"
        "Voted against party majority: Massie (R-KY-4)\n"
        "yeasandnaysdata.com/votes/119/house/2/317/"
    )


def test_nomination_post_with_tie_break():
    vote = senate_vote()
    totals = {"R": {"yes": 50, "no": 3}, "D": {"no": 45}, "I": {"no": 2}}
    against = ["Collins (R-ME)", "McConnell (R-KY)", "Murkowski (R-AK)"]
    text = format_post(doc(vote, against=against, party_totals=totals), decide(vote))
    assert text.splitlines() == [
        "Senate confirms Peter Hegseth as Secretary of Defense",
        "50 Yea · 50 Nay · Vice President voted Yea to break the tie",
        "D 0–45 · I 0–2 · R 50–3",
        "Voted against party majority: Collins (R-ME), McConnell (R-KY), Murkowski (R-AK)",
        "yeasandnaysdata.com/votes/119/senate/1/15/",
    ]


@pytest.mark.parametrize("vote_title, expected", [
    ("Motion to Invoke Cloture: Motion to Proceed to S. 5",
     "Senate invokes cloture on Motion to Proceed to S. 5"),
    ("Motion to Invoke Cloture on the Motion to Proceed to H.R. 2347",
     "Senate invokes cloture on Motion to Proceed to H.R. 2347"),
    ("Motion to Invoke Cloture on the Motion to Proceed: H.R. 7008",
     "Senate invokes cloture on Motion to Proceed to H.R. 7008"),
    ("Motion to Invoke Cloture: Motion to proceed to S. 1582",
     "Senate invokes cloture on Motion to Proceed to S. 1582"),
    ("Motion to Invoke Cloture Re: Amdt. No. 4308",
     "Senate invokes cloture on Amdt. No. 4308"),
    ("Upon Reconsideration, Motion to Invoke Cloture Re: Motion to Proceed to H.R. 7147",
     "Senate invokes cloture on Motion to Proceed to H.R. 7147, Upon Reconsideration"),
    ("Upon Reconsideration: Motion to Invoke Cloture on the Motion to Proceed to H.R. 5371",
     "Senate invokes cloture on Motion to Proceed to H.R. 5371, Upon Reconsideration"),
    ("Motion to Invoke Cloture: Motion to Proceed to S. 3012, Upon Reconsideration",
     "Senate invokes cloture on Motion to Proceed to S. 3012, Upon Reconsideration"),
    ("Upon reconsideration, Motion to invoke cloture on the Motion to Proceed to H.R. 1",
     "Senate invokes cloture on Motion to Proceed to H.R. 1, Upon Reconsideration"),
    ("Motion to Invoke Cloture: Todd Blanche to be Attorney General",
     "Senate invokes cloture on Todd Blanche to be Attorney General"),
])
def test_cloture_headline_uses_one_form(vote_title, expected):
    vote = senate_vote(question="On the Cloture Motion", result="Cloture Motion Agreed to",
                       vote_title=vote_title, tie_breaker_by=None, tie_breaker_vote=None)
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == expected


@pytest.mark.parametrize("measure_title, expected", [
    ("  An Act  ", 'House passes H.R. 1, "An Act"'),
    ("   ", "House passes H.R. 1"),
    ("", "House passes H.R. 1"),
    (None, "House passes H.R. 1"),
])
def test_passage_headline_trims_title_and_cites_measure_alone_without_one(measure_title, expected):
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=measure_title)
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == expected


def test_cloture_headline_falls_back_to_measure_title_when_vote_title_is_blank():
    vote = senate_vote(question="On the Cloture Motion", result="Cloture Motion Agreed to", vote_title="   ",
                       measure_title=" Peter Hegseth, of Tennessee, to be Secretary of Defense ",
                       tie_breaker_by=None, tie_breaker_vote=None)
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == (
        "Senate invokes cloture on Peter Hegseth, of Tennessee, to be Secretary of Defense")


def test_cloture_headline_trims_a_padded_vote_title():
    vote = senate_vote(question="On the Cloture Motion", result="Cloture Motion Agreed to",
                       vote_title="  Motion to Invoke Cloture: Motion to Proceed to S. 5  ",
                       tie_breaker_by=None, tie_breaker_vote=None)
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == (
        "Senate invokes cloture on Motion to Proceed to S. 5")


def test_nomination_headline_trims_a_padded_title():
    vote = senate_vote(measure_title="  Peter Hegseth, of Tennessee, to be Secretary of Defense  ")
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == (
        "Senate confirms Peter Hegseth as Secretary of Defense")


@pytest.mark.parametrize("measure_title", ["", "   ", None])
def test_nomination_headline_cites_the_number_without_a_title(measure_title):
    vote = senate_vote(measure_title=measure_title, measure_number=" PN11-7 ")
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == "Senate confirms PN11-7"


def test_cloture_headline_cites_the_measure_without_a_title():
    vote = senate_vote(question="On the Cloture Motion", result="Cloture Motion Agreed to", vote_title=" ",
                       measure_title=None, measure_number="PN11-7", tie_breaker_by=None, tie_breaker_vote=None)
    assert format_post(doc(vote), decide(vote)).splitlines()[0] == "Senate invokes cloture on PN11-7"


@pytest.mark.parametrize("vote", [
    senate_vote(measure_title="  ", measure_number=None),
    senate_vote(measure_title=None, measure_number="  ", vote_title="On the Nomination: Peter Hegseth"),
    senate_vote(question="On the Cloture Motion", result="Cloture Motion Agreed to",
                vote_title=None, measure_title=" ", measure_number=None),
])
def test_nomination_or_cloture_with_nothing_to_cite_is_skipped(vote):
    decision = decide(vote)
    assert not decision.post
    assert decision.reason.endswith("to cite")


def test_no_party_break_line_when_nobody_broke():
    vote = senate_vote(tie_breaker_by=None, tie_breaker_vote=None, yea_count=51, nay_count=49)
    assert "Voted against" not in format_post(doc(vote), decide(vote))


def test_tally_uses_recorded_terms_and_only_nonzero_present_and_not_voting():
    vote = house_vote(present_count=1, not_voting_count=0)
    assert tally_line(vote, {"A": "Aye", "B": "No"}) == "211 Aye · 204 No · 1 Present"
    assert tally_line(house_vote(not_voting_count=18), {"A": "Yea"}) == "211 Yea · 204 Nay · 18 Not Voting"


def test_party_line_shows_d_and_r_always_and_i_only_when_an_independent_voted():
    assert party_line({"R": {"yes": 211, "not_voting": 7}, "D": {"yes": 83, "no": 128}}) == "D 83–128 · R 211–0"
    assert party_line({"R": {"yes": 1}, "D": {"no": 1}, "I": {"not_voting": 1}}) == "D 0–1 · R 1–0"
    assert party_line({"R": {"yes": 1}, "D": {"no": 1}, "I": {"no": 2}}) == "D 0–1 · I 0–2 · R 1–0"
    assert party_line({}) == "D 0–0 · R 0–0"


def test_party_break_names_only_when_one_to_five_members():
    labels = [f"M{i} (R-TX-{i})" for i in range(1, 7)]
    assert party_break_line([]) is None
    assert party_break_line(labels[:5]) == (
        "Voted against party majority: M1 (R-TX-1), M2 (R-TX-2), M3 (R-TX-3), M4 (R-TX-4), M5 (R-TX-5)"
    )
    assert party_break_line(labels) is None


def test_more_than_five_against_majority_omits_names_line():
    vote = house_vote(question="On Passage", measure_number="H R 1013", measure_title="An Act")
    totals = {"R": {"yes": 211}, "D": {"yes": 83, "no": 128}, "I": {"yes": 1}}
    text = format_post(doc(vote, against=[f"M{i} (D-CA-{i})" for i in range(83)], party_totals=totals),
                       decide(vote))
    assert "Voted against" not in text
    assert text.splitlines()[2] == "D 83–128 · I 1–0 · R 211–0"


def test_long_post_truncates_title_and_keeps_every_other_line():
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title="An Act " + "word " * 80)
    labels = [f"Member{i} (D-CA-{i})" for i in range(1, 6)]
    text = format_post(doc(vote, against=labels), decide(vote))
    lines = text.splitlines()
    assert len(text) <= 300
    assert lines[0].endswith('…"')
    assert lines[1:] == [
        "211 Yea · 204 Nay",
        "D 0–1 · R 1–0",
        "Voted against party majority: " + ", ".join(labels),
        "yeasandnaysdata.com/votes/119/house/2/317/",
    ]


def test_truncation_cuts_at_a_word_boundary():
    vote = house_vote(question="On Passage", measure_number="H R 1",
                      measure_title="An Act " + "Housing " * 40)
    labels = [f"Member{i} (D-CA-{i})" for i in range(1, 6)]
    headline = format_post(doc(vote, against=labels), decide(vote)).splitlines()[0]
    assert headline.endswith(' Housing…"')


def test_post_that_cannot_fit_raises_instead_of_running_long():
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title="Word " * 30)
    with pytest.raises(PostTooLong):
        format_post(doc(vote), decide(vote), max_length=41)
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title="Word Word")
    with pytest.raises(PostTooLong):
        format_post(doc(vote), decide(vote), max_length=60)


def test_one_very_long_word_is_cut_rather_than_rejected():
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title="A " + "x" * 400)
    text = format_post(doc(vote), decide(vote))
    assert len(text) <= 300 and text.splitlines()[0].endswith('x…"')


def test_cut_just_before_a_comma_keeps_the_whole_word():
    vote = house_vote(question="On Passage", measure_number="H R 1",
                      measure_title="Motion to Proceed to H.R. 5371, and a long tail " + "y" * 300)
    full = format_post(doc(vote), decide(vote), max_length=1000)
    cut_at_comma = len(full) - len(" and a long tail " + "y" * 300) - 1 + len("…")
    headline = format_post(doc(vote), decide(vote), max_length=cut_at_comma).splitlines()[0]
    assert headline.endswith('H.R. 5371…"')


def cut_after(vote, prefix, tail):
    """Headline of `vote` when the post is just long enough to keep `prefix`
    of a title `prefix + tail`, cut mid-word in the word that follows."""
    full = format_post(doc(vote), decide(vote), max_length=1000)
    max_length = len(full) - len(tail) + len("…") + 2
    return format_post(doc(vote), decide(vote), max_length=max_length).splitlines()[0]


def test_cut_drops_a_trailing_small_word():
    prefix, tail = "An Act relating to the Secretary of", " Defense and a long tail " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_after(vote, prefix, tail).endswith(' Secretary…"')


def test_cut_drops_several_trailing_small_words():
    prefix, tail = "An Act to provide funds to the", " States and a long tail " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_after(vote, prefix, tail).endswith(' funds…"')


def test_small_word_stays_when_dropping_it_leaves_too_little_title():
    prefix, tail = "Housing Supply Act Of", " Housing and a long tail " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_after(vote, prefix, tail).endswith(' Act Of…"')


def cut_at(vote, prefix, tail):
    """Headline of `vote` when the post is just long enough to keep exactly
    `prefix` of a title `prefix + tail` before the ellipsis."""
    full = format_post(doc(vote), decide(vote), max_length=1000)
    max_length = len(full) - len(tail) + len("…")
    text = format_post(doc(vote), decide(vote), max_length=max_length)
    assert len(text) <= max_length
    return text.splitlines()[0]


@pytest.mark.parametrize("prefix, tail, ending", [
    ("Should the Senate concur in the amendment", "? And a long tail ", ' the amendment…"'),
    # Closing the parenthesis takes one more character, so the cut moves back a word.
    ("An Act to amend title 5 (the Housing Act", ") and a long tail ", ' (the Housing…)"'),
    ("An Act relating to benefits for veterans", "’ survivors and a long tail ", ' for veterans…"'),
    # A period mostly ends an abbreviation, so the abbreviated word goes too.
    ("An Act to amend the provisions of H.R", ". 5371 and a long tail ", ' provisions…"'),
    ("An Act relating to Section 5 of the U.S", ". Code and a long tail ", ' Section 5…"'),
    ("To name the post office in Saint Louis and St", ". Louis County and a long tail ", ' Saint Louis…"'),
])
def test_cut_just_before_closing_punctuation_keeps_the_whole_word(prefix, tail, ending):
    tail += "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(ending)


def test_cut_inside_a_curly_quoted_name_closes_the_quote():
    prefix, tail = "Disapproving the rule relating to “California State Non", "road Standards” " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H J RES 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(' “California State…”"')


def test_closing_quote_that_does_not_fit_takes_a_shorter_cut():
    # The cut falls exactly at a word end, with no room left for the quote.
    prefix, tail = "Disapproving the rule relating to “California State", " Nonroad Standards” " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H J RES 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(' “California…”"')


@pytest.mark.parametrize("prefix, tail, ending", [
    ("An Act to amend title 5 (the Housing Supp", "ly Act) and ", ' (the Housing…)"'),
    ('Disapproving the rule relating to "California State Non', 'road Standards" ', ' "California State…""'),
    ("An Act to amend title 5 (the “Fair Housing Non", "road Act”) and ", ' (the “Fair Housing…”)"'),
    ("Disapproving the rule relating to ‘California State Non", "road Standards’ ", ' ‘California State…’"'),
])
def test_cut_inside_parentheses_or_quotes_closes_them(prefix, tail, ending):
    tail += "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(ending)


@pytest.mark.parametrize("text, marks", [
    ("no marks at all", ""),
    ("closed (marks) and “quotes” and ‘single’ and \"straight\"", ""),
    # Nested marks close innermost first.
    ("(the “Fair ‘Housing", "’”)"),
    ('(a "b', '")'),
    # A closing mark closes the open mark it matches, even past an inner one.
    ("“a (b ” c", ")"),
    ('"a (b " c', ")"),
    ("(a “b ) c", "”"),
    # A stray closing mark is ignored.
    ("1) foo", ""),
    ("“a ’ b) c", "”"),
    # An apostrophe between letters or digits doesn't close a single quote.
    ("the ‘Children’s Act", "’"),
    ("the ‘Children’s Act’ and", ""),
    ("the ‘1990’s Act", "’"),
    # Senate titles quote a short title with doubled marks.
    ("to ‘‘THE ONE, BIG", "’’"),
    ("to ‘‘THE ONE’’ and", ""),
    # One after a plural closes it, as a closing quote would.
    ("the ‘Veterans’ benefits", ""),
])
def test_closing_marks(text, marks):
    assert closing_marks(text) == marks


@pytest.mark.parametrize("prefix, tail, ending", [
    ("An Act to amend the provisions of H.R.", " 5371 and a long tail ", ' provisions…"'),
    # An abbreviation that ends a word cut leaves its period too.
    ("To name the post office in Saint Louis and St. Lou", "is County and a long tail ", ' Saint Louis…"'),
    # Dropping a small word can bare an abbreviation, which goes too.
    ("A bill to amend title 5, U.S.C. and", " so on and a long tail ", ' title 5…"'),
    # A period that ends a sentence goes the same way.
    ("To amend the Internal Revenue Code of 1986.", " And a long tail ", ' Revenue Code…"'),
])
def test_cut_just_after_a_period_drops_the_abbreviated_word(prefix, tail, ending):
    tail += "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(ending)


def test_cut_exactly_after_a_small_word_drops_it():
    prefix, tail = "An Act relating to the Secretary of", " Defense and a long tail " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(' Secretary…"')


def test_small_word_after_a_quote_mark_is_dropped():
    prefix, tail = 'To designate the facility as "The', ' Liberty Building" and a long tail ' + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(' facility as…"')


def test_mid_word_cut_too_short_to_move_back_keeps_a_small_word_start():
    # Moving back to "Housing Supply Act" leaves too little title, so the cut
    # stays inside "forestry", and its "for" is not a small word to drop.
    prefix, tail = "Housing Supply Act for", "estry and a long tail " + "y" * 300
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title=prefix + tail)
    assert cut_at(vote, prefix, tail).endswith(' Act for…"')


def test_reconsideration_is_dropped_before_the_title_is_cut():
    vote = senate_vote(question="On the Cloture Motion", result="Cloture Motion Rejected",
                       vote_title="Upon Reconsideration, Motion to Invoke Cloture on the Motion to Proceed to H.R. 5371",
                       tie_breaker_by=None, tie_breaker_vote=None)
    labels = [f"Member{i} (D-CA)" for i in range(1, 6)]
    full = format_post(doc(vote, against=labels), decide(vote), max_length=1000)
    text = format_post(doc(vote, against=labels), decide(vote), max_length=len(full) - 1)
    assert text.splitlines()[0] == "Senate fails to invoke cloture on Motion to Proceed to H.R. 5371"


# --- state: nothing double-posts ----------------------------------------

def test_vote_order_crosses_sessions():
    assert bot_state.is_new("h119-2-0001", "h119-1-0362")
    assert not bot_state.is_new("h119-1-0362", "h119-1-0362")
    assert bot_state.is_new("h119-1-0001", None)


@pytest.fixture
def out_dir(tmp_path):
    votes = [
        house_vote(vote_id="h119-2-0316", roll_number=316, vote_date="2026-11-09", vote_time_et="2026-11-09T18:00:00"),
        house_vote(),
        senate_vote(vote_id="s119-2-0257", session=2, roll_number=257, vote_date="2026-11-09",
                    vote_time_et="2026-11-09T17:00:00"),
    ]
    (tmp_path / "votes").mkdir()
    (tmp_path / "votes.json").write_text(json.dumps({"votes": votes}))
    for v in votes:
        (tmp_path / "votes" / f"{v['vote_id']}.json").write_text(json.dumps(doc(v)))
    return tmp_path


def test_init_marks_latest_vote_per_chamber_and_nothing_is_pending(out_dir, tmp_path):
    state_path = tmp_path / "state.json"
    assert bot.init(state_path, out_dir) == {"house": "h119-2-0317", "senate": "s119-2-0257"}
    assert bot.pending(bot_state.load(state_path), out_dir) == []


def test_pending_returns_only_votes_after_state_in_order(out_dir):
    pending = bot.pending({"house": "h119-2-0316", "senate": "s119-2-0257"}, out_dir)
    assert [v["vote_id"] for v in pending] == ["h119-2-0317"]


def test_run_without_state_refuses_rather_than_queueing_everything(out_dir, tmp_path):
    with pytest.raises(SystemExit, match="yan bot init"):
        bot.run(tmp_path / "missing.json", out_dir)


def test_dry_run_does_not_advance_state(out_dir, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    before = state_path.read_text()
    bot.run(state_path, out_dir)
    assert "h119-2-0317" in capsys.readouterr().out
    assert state_path.read_text() == before


# --- publishing (fake publisher; nothing leaves the test) ----------------

class FakePublisher:
    def __init__(self, already=()):
        self.posts = []
        self.already = set(already)

    def recent_links(self):
        return self.already

    def post(self, text, url):
        self.posts.append((text, url))


def publish_run(out_dir, state_path, publisher, today="2026-11-11", sleeps=None, page_live=lambda url: True):
    bot.run(state_path, out_dir, publish=True, publisher=publisher,
            sleep=(sleeps.append if sleeps is not None else lambda s: None),
            today=__import__("datetime").date.fromisoformat(today), page_live=page_live)


def test_publish_posts_in_order_and_advances_state(out_dir, tmp_path):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0300", "senate": "s119-2-0200"}, state_path)
    publisher, sleeps = FakePublisher(), []
    publish_run(out_dir, state_path, publisher, sleeps=sleeps)

    assert [url for _, url in publisher.posts] == [
        "https://yeasandnaysdata.com/votes/119/senate/2/257/",
        "https://yeasandnaysdata.com/votes/119/house/2/316/",
        "https://yeasandnaysdata.com/votes/119/house/2/317/",
    ]
    assert sleeps == [bot.POST_INTERVAL_SECONDS] * 2  # between posts, not before the first
    assert bot_state.load(state_path) == {"house": "h119-2-0317", "senate": "s119-2-0257"}

    # A second run has nothing left to post.
    again = FakePublisher()
    publish_run(out_dir, state_path, again)
    assert again.posts == []


def test_publish_skips_votes_already_on_bluesky_but_advances_state(out_dir, tmp_path):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    publisher = FakePublisher(already={"yeasandnaysdata.com/votes/119/house/2/317/"})
    publish_run(out_dir, state_path, publisher)
    assert publisher.posts == []
    assert bot_state.load(state_path)["house"] == "h119-2-0317"


def test_publish_recognizes_earlier_posts_that_linked_the_official_record(out_dir, tmp_path):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    publisher = FakePublisher(already={"clerk.house.gov/Votes/2026317"})
    publish_run(out_dir, state_path, publisher)
    assert publisher.posts == []
    assert bot_state.load(state_path)["house"] == "h119-2-0317"


def test_publish_waits_for_a_vote_page_that_is_not_live_and_keeps_order(out_dir, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0300", "senate": "s119-2-0200"}, state_path)
    publisher, checked = FakePublisher(), []

    def page_live(url):
        checked.append(url)
        return not url.endswith("/house/2/316/")

    publish_run(out_dir, state_path, publisher, page_live=page_live)

    # The senate vote posts; h119-2-0316's page isn't up, so it and the vote after it wait.
    assert [url for _, url in publisher.posts] == ["https://yeasandnaysdata.com/votes/119/senate/2/257/"]
    assert checked[-1] == "https://yeasandnaysdata.com/votes/119/house/2/316/"
    assert bot_state.load(state_path) == {"house": "h119-2-0300", "senate": "s119-2-0257"}
    assert "page not live yet" in capsys.readouterr().out

    # Once the page is live, the next run picks up where this one stopped.
    later = FakePublisher()
    publish_run(out_dir, state_path, later)
    assert [url for _, url in later.posts] == [
        "https://yeasandnaysdata.com/votes/119/house/2/316/",
        "https://yeasandnaysdata.com/votes/119/house/2/317/",
    ]


def test_a_house_page_not_live_holds_back_a_later_senate_vote(out_dir, tmp_path, capsys):
    senate = senate_vote(vote_id="s119-2-0258", session=2, roll_number=258, vote_date="2026-11-10",
                         vote_time_et="2026-11-10T16:00:00")
    votes = json.loads((out_dir / "votes.json").read_text())["votes"] + [senate]
    (out_dir / "votes.json").write_text(json.dumps({"votes": votes}))
    (out_dir / "votes" / "s119-2-0258.json").write_text(json.dumps(doc(senate)))
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    publisher, checked = FakePublisher(), []

    def page_live(url):
        checked.append(url)
        return "/house/" not in url

    publish_run(out_dir, state_path, publisher, page_live=page_live)

    # Posts stay in order across chambers: the Senate vote's page is live but
    # it came after h119-2-0317, so it waits too, and neither chamber's state moves.
    assert publisher.posts == []
    assert checked == ["https://yeasandnaysdata.com/votes/119/house/2/317/"]
    assert bot_state.load(state_path) == {"house": "h119-2-0316", "senate": "s119-2-0257"}


def test_a_vote_page_that_never_goes_live_stalls_the_bot_until_the_backlog_is_too_old(out_dir, tmp_path):
    # Known gap (BOARD.md Later): the wait has no bound of its own, so the bot
    # holds every later vote until MAX_BACKLOG_AGE stops it. h119-2-0317 is
    # from 2026-11-10.
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    publisher = FakePublisher()
    for today in ["2026-11-11", "2026-11-12", "2026-11-13"]:
        publish_run(out_dir, state_path, publisher, today=today, page_live=lambda url: False)
    assert publisher.posts == []
    assert bot_state.load(state_path)["house"] == "h119-2-0316"

    with pytest.raises(SystemExit, match="older than 3 days"):
        publish_run(out_dir, state_path, publisher, today="2026-11-14", page_live=lambda url: False)


def test_vote_page_url_matches_the_site_route():
    # The same cases are checked against the site's Yan.vote_url in
    # site/test/yan_data_test.rb, so the bot never links a path the site doesn't build.
    cases = json.loads((FIXTURES / "vote_urls.json").read_text())
    assert cases
    for case in cases:
        assert vote_page_url(case["vote"]) == SITE_URL + case["path"]


def test_is_live_only_for_a_200_on_the_same_host_and_logs_why_not(monkeypatch, capsys):
    import httpx

    # Requested URL -> (status, URL it ended at after redirects).
    responses = {
        "https://a.test/": (200, "https://a.test/"),
        "http://a.test/old/": (200, "https://a.test/new/"),
        "https://b.test/": (404, "https://b.test/"),
        "https://lapsed.test/": (200, "https://parked.test/lander"),
    }
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        if url not in responses:
            raise httpx.ConnectError("down")
        status, final = responses[url]
        return httpx.Response(status, request=httpx.Request("GET", final))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert bot.is_live("https://a.test/")
    assert bot.is_live("http://a.test/old/")
    assert not bot.is_live("https://b.test/")
    assert not bot.is_live("https://c.test/")
    assert not bot.is_live("https://lapsed.test/")
    assert all(kwargs["follow_redirects"] for kwargs in calls)
    out = capsys.readouterr().out
    assert "https://b.test/: HTTP 404" in out
    assert "https://lapsed.test/: redirected to another host (parked.test)" in out
    assert "https://c.test/: ConnectError" in out


def test_publish_stops_at_post_limit_and_leaves_rest_for_next_run(out_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "MAX_POSTS_PER_RUN", 1)
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0300", "senate": "s119-2-0200"}, state_path)
    publisher = FakePublisher()
    publish_run(out_dir, state_path, publisher)
    assert len(publisher.posts) == 1
    assert bot_state.load(state_path) == {"house": "h119-2-0300", "senate": "s119-2-0257"}


def test_publish_skips_a_vote_too_long_to_post_and_keeps_going(out_dir, tmp_path, capsys):
    # Five long names fill the post, leaving no room for the title.
    long_names = [f"Member{i} " + "x" * 60 for i in range(5)]
    (out_dir / "votes" / "h119-2-0316.json").write_text(json.dumps(doc(
        house_vote(vote_id="h119-2-0316", roll_number=316), against=long_names)))
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0300", "senate": "s119-2-0257"}, state_path)
    publisher = FakePublisher()
    publish_run(out_dir, state_path, publisher)

    assert [url for _, url in publisher.posts] == ["https://yeasandnaysdata.com/votes/119/house/2/317/"]
    assert bot_state.load(state_path)["house"] == "h119-2-0317"
    assert "too long to post in 300 characters" in capsys.readouterr().out


def test_dry_run_shows_a_vote_too_long_to_post_as_skipped(out_dir, tmp_path, capsys):
    long_names = [f"Member{i} " + "x" * 60 for i in range(5)]
    (out_dir / "votes" / "h119-2-0317.json").write_text(json.dumps(doc(house_vote(), against=long_names)))
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    bot.run(state_path, out_dir)
    out = capsys.readouterr().out
    assert "[too long to post in 300 characters]\n(skipped)" in out


def test_publish_refuses_a_stale_backlog(out_dir, tmp_path):
    state_path = tmp_path / "state.json"
    bot_state.save({"house": "h119-2-0316", "senate": "s119-2-0257"}, state_path)
    publisher = FakePublisher()
    with pytest.raises(SystemExit, match="yan bot init"):
        publish_run(out_dir, state_path, publisher, today="2026-12-01")
    assert publisher.posts == []


def test_publisher_requires_credentials_and_never_logs_them(monkeypatch):
    from yan.bot.publish import BlueskyPublisher, MissingCredentials

    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    with pytest.raises(MissingCredentials):
        BlueskyPublisher(client=object())

    class FailingClient:
        def login(self, handle, password):
            raise ValueError(f"bad login for {handle} with {password}")

    monkeypatch.setenv("BLUESKY_HANDLE", "example.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "secret-value")
    with pytest.raises(RuntimeError) as err:
        BlueskyPublisher(client=FailingClient())
    assert "secret-value" not in str(err.value) and err.value.__cause__ is None


def test_publisher_feed_and_post_errors_give_only_type_and_status(monkeypatch):
    from yan.bot.publish import BlueskyPublisher

    class Response:
        status_code = 502

    class SDKError(Exception):
        response = Response()

    class FailingClient:
        def login(self, handle, password):
            pass

        def get_author_feed(self, actor, limit):
            raise SDKError(f"feed for {actor}: response body")

        def send_post(self, builder, langs):
            raise SDKError(f"rejected {builder.build_text()}: response body")

    monkeypatch.setenv("BLUESKY_HANDLE", "example.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "x")
    publisher = BlueskyPublisher(client=FailingClient())
    with pytest.raises(RuntimeError) as err:
        publisher.recent_links()
    assert str(err.value) == "Bluesky feed read failed (SDKError, HTTP 502)" and err.value.__cause__ is None
    with pytest.raises(RuntimeError) as err:
        publisher.post("House passes H.R. 1\nclerk.house.gov/Votes/1", "https://clerk.house.gov/Votes/1")
    assert str(err.value) == "Bluesky post failed (SDKError, HTTP 502)" and err.value.__cause__ is None


def test_publisher_links_the_last_line_to_the_full_url(monkeypatch):
    from yan.bot.publish import BlueskyPublisher

    class RecordingClient:
        def login(self, handle, password):
            pass

        def send_post(self, builder, langs):
            self.text, self.facets, self.langs = builder.build_text(), builder.build_facets(), langs

    monkeypatch.setenv("BLUESKY_HANDLE", "example.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "x")
    client = RecordingClient()
    text = "House passes H.R. 1\n211 Yea · 204 Nay\nclerk.house.gov/Votes/2026317"
    BlueskyPublisher(client=client).post(text, "https://clerk.house.gov/Votes/2026317")

    assert client.text == text
    [facet] = client.facets
    assert facet.features[0].uri == "https://clerk.house.gov/Votes/2026317"
    linked = text.encode()[facet.index.byte_start:facet.index.byte_end].decode()
    assert linked == "clerk.house.gov/Votes/2026317"
