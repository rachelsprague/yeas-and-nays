import json

import pytest

from yan.bot import run as bot
from yan.bot import state as bot_state
from yan.bot.format import format_post, party_break_line, tally_line
from yan.bot.rules import decide, measure_label


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


def doc(vote, against=(), positions=None):
    return {
        "vote": vote,
        "against_party_majority": [{"member_label": label} for label in against],
        "positions": positions or {"A000001": "Yea"},
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
    text = format_post(doc(vote, against=["Massie (R-KY-4)"]), decide(vote))
    assert text == (
        'House agrees to motion to refer H.Res. 1655, "Impeaching Peter Brian Hegseth, '
        'Secretary of Defense, for high crimes and misdemeanors"\n'
        "211 Yea · 204 Nay · 18 Not Voting\n"
        "Voted against party majority: Massie (R-KY-4)\n"
        "clerk.house.gov/Votes/2026317"
    )


def test_nomination_post_with_tie_break():
    vote = senate_vote()
    text = format_post(doc(vote, against=["Collins (R-ME)", "McConnell (R-KY)", "Murkowski (R-AK)"]), decide(vote))
    assert text.splitlines() == [
        "Senate confirms Peter Hegseth as Secretary of Defense",
        "50 Yea · 50 Nay · Vice President voted Yea to break the tie",
        "Voted against party majority: Collins (R-ME), McConnell (R-KY), Murkowski (R-AK)",
        "senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00015.htm",
    ]


def test_no_party_break_line_when_nobody_broke():
    vote = senate_vote(tie_breaker_by=None, tie_breaker_vote=None, yea_count=51, nay_count=49)
    assert "Voted against" not in format_post(doc(vote), decide(vote))


def test_tally_uses_recorded_terms_and_only_nonzero_present_and_not_voting():
    vote = house_vote(present_count=1, not_voting_count=0)
    assert tally_line(vote, {"A": "Aye", "B": "No"}) == "211 Aye · 204 No · 1 Present"
    assert tally_line(house_vote(not_voting_count=18), {"A": "Yea"}) == "211 Yea · 204 Nay · 18 Not Voting"


def test_party_break_line_lists_five_then_counts_the_rest():
    labels = [f"M{i} (R-TX-{i})" for i in range(1, 8)]
    assert party_break_line(labels) == (
        "Voted against party majority: M1 (R-TX-1), M2 (R-TX-2), M3 (R-TX-3), M4 (R-TX-4), M5 (R-TX-5) and 2 others"
    )
    assert party_break_line(labels[:6]).endswith("and 1 other")


def test_long_post_truncates_title_and_keeps_tally_and_link():
    vote = house_vote(question="On Passage", measure_number="H R 1", measure_title="An Act " + "word " * 80)
    labels = [f"Member{i} (D-CA-{i})" for i in range(1, 30)]
    text = format_post(doc(vote, against=labels), decide(vote))
    lines = text.splitlines()
    assert len(text) <= 300
    assert lines[0].endswith('…"')
    assert lines[1] == "211 Yea · 204 Nay"
    assert lines[2].startswith("Voted against party majority: ") and "others" in lines[2]
    assert lines[-1] == "clerk.house.gov/Votes/2026317"


# --- state: nothing double-posts ----------------------------------------

def test_vote_order_crosses_sessions():
    assert bot_state.is_new("h119-2-0001", "h119-1-0362")
    assert not bot_state.is_new("h119-1-0362", "h119-1-0362")
    assert bot_state.is_new("h119-1-0001", None)


@pytest.fixture
def out_dir(tmp_path):
    votes = [
        house_vote(vote_id="h119-2-0316", roll_number=316, vote_time_et="2026-11-09T18:00:00"),
        house_vote(),
        senate_vote(vote_id="s119-2-0257", session=2, roll_number=257, vote_time_et="2026-11-09T17:00:00"),
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
