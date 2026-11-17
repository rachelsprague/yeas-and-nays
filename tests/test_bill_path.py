import datetime as dt

from yan.export.bill_path import vote_path


def d(text):
    return dt.date.fromisoformat(text)


def m(**dates):
    """Milestones: name=date or name=(first, last)."""
    return {k: (d(v), d(v)) if isinstance(v, str) else (d(v[0]), d(v[1])) for k, v in dates.items()}


def vote(bill_type="hr", chamber="house", date="2025-05-22", question="On Passage", title="An Act"):
    return {"bill_type": bill_type, "chamber": chamber, "vote_date": d(date), "question": question,
            "measure_title": title}


def steps(path):
    return [(s["key"], s["label"], s["status"], s["date"]) for s in path["steps"]]


def current(path):
    return [s["key"] for s in path["steps"] if s["current"]]


# H.R. 1 (119th): every step, from Congress.gov's actions.
HR1 = m(introduced="2025-05-20", committee="2025-05-20", passed_house="2025-05-22", passed_senate="2025-07-01",
        differences="2025-07-03", presented="2025-07-03", became_law="2025-07-04")


def test_a_bill_that_became_law_has_every_step_done():
    path = vote_path(vote(), HR1)
    assert path["track"] == "law"
    assert steps(path) == [
        ("introduced", "Introduced", "done", "2025-05-20"),
        ("committee", "Committee", "done", "2025-05-20"),
        ("passed_house", "Passed House", "done", "2025-05-22"),
        ("passed_senate", "Passed Senate", "done", "2025-07-01"),
        ("differences", "Differences resolved", "done", "2025-07-03"),
        ("presented", "To President", "done", "2025-07-03"),
        ("became_law", "Became law", "done", "2025-07-04"),
    ]


def test_each_vote_is_placed_at_the_step_it_was_taken_at():
    # House passage, on the day the House passed it.
    assert current(vote_path(vote(date="2025-05-22"), HR1)) == ["passed_house"]
    # A rule or motion before passage in the House.
    assert current(vote_path(vote(date="2025-05-21", question="On Motion to Recommit"), HR1)) == ["passed_house"]
    # The Senate's votes, after the House passed it.
    assert current(vote_path(vote(chamber="senate", date="2025-06-30", question="On the Motion"), HR1)) == ["passed_senate"]
    # The House agreeing to the Senate amendment.
    concur = vote(date="2025-07-03", question="On Motion to Concur in the Senate Amendment")
    assert current(vote_path(concur, HR1)) == ["differences"]


def test_a_vote_before_congress_gov_records_the_step_still_moves_the_path():
    # The House passed it today (the vote itself); Congress.gov hasn't caught up.
    path = vote_path(vote(date="2026-11-10"), m(introduced="2026-10-01", passed_house="2026-11-10"))
    assert [s[2] for s in steps(path)] == ["done", "done", "done", "upcoming", "upcoming", "upcoming", "upcoming"]
    # Committee is reached (undated): the House passed it.
    assert steps(path)[1] == ("committee", "Committee", "done", None)
    assert current(path) == ["passed_house"]


def test_differences_are_skipped_when_the_second_chamber_passed_the_same_text():
    path = vote_path(vote(), m(passed_house="2023-04-28", passed_senate="2023-05-03", presented="2023-05-09"))
    assert dict((k, s) for k, _, s, _ in steps(path))["differences"] == "skipped"


def test_differences_in_progress_until_sent_to_the_president():
    path = vote_path(vote(chamber="senate", date="2026-10-01", question="On the Motion to Concur in the House Amendment"),
                     m(passed_house="2026-06-01", passed_senate="2026-07-01", differences=("2026-09-01", "2026-10-01")))
    differences = path["steps"][4]
    assert (differences["status"], differences["date"], differences["current"]) == ("in_progress", "2026-10-01", True)


# H.J.Res. 39 (118th): vetoed, and the House override failed.
HJRES39 = m(introduced="2023-03-07", committee="2023-04-21", passed_house="2023-04-28", passed_senate="2023-05-03",
            presented="2023-05-09", vetoed="2023-05-16", override_failed_house="2023-05-24")


def test_a_veto_and_a_failed_override():
    path = vote_path(vote(bill_type="hjres", date="2023-05-24",
                          question="Passage, Objections of the President To The Contrary Notwithstanding"), HJRES39)
    assert steps(path)[5:] == [
        ("presented", "To President", "done", "2023-05-09"),
        ("vetoed", "Vetoed", "failed", "2023-05-16"),
        ("override", "Veto override failed", "failed", "2023-05-24"),
    ]
    assert current(path) == ["override"]


def test_an_override_vote_alone_shows_the_bill_was_vetoed():
    # H.R. 131 (119th): only this site's override vote, before Congress.gov's actions are in.
    path = vote_path(vote(date="2026-01-08", question="Passage, Objections of the President To The Contrary Notwithstanding"),
                     m(override_failed_house="2026-01-08"))
    assert [(k, s) for k, _, s, _ in steps(path)] == [
        ("introduced", "done"), ("committee", "done"), ("passed_house", "done"), ("passed_senate", "done"),
        ("differences", "skipped"), ("presented", "done"), ("vetoed", "failed"), ("override", "failed"),
    ]


def test_an_override_that_passed_ends_in_law():
    path = vote_path(vote(), m(presented="2026-01-01", vetoed="2026-01-05", override_passed_house="2026-02-01",
                               override_passed_senate="2026-02-03", became_law="2026-02-03"))
    assert steps(path)[-2:] == [("override", "Veto override", "done", "2026-02-03"),
                                ("became_law", "Became law", "done", "2026-02-03")]


def test_a_pocket_veto_ends_the_path():
    path = vote_path(vote(), m(presented="2026-12-20", pocket_vetoed="2027-01-02"))
    assert steps(path)[-1] == ("pocket_vetoed", "Pocket vetoed", "failed", "2027-01-02")


def test_a_failed_passage_vote_stops_the_path_until_it_passes():
    failed = m(introduced="2025-01-03", committee="2026-07-06", failed_house="2026-09-02")
    path = vote_path(vote(bill_type="hjres", date="2026-09-02"), failed)
    assert steps(path)[2] == ("passed_house", "Failed in House", "failed", "2026-09-02")
    assert all(s == "upcoming" for _, _, s, _ in steps(path)[3:])
    # Passed later (e.g. under a rule after a failed suspension vote): passage wins.
    path = vote_path(vote(bill_type="hjres"), {**failed, **m(passed_house="2026-09-20")})
    assert steps(path)[2] == ("passed_house", "Passed House", "done", "2026-09-20")


# H.Con.Res. 89 (119th): agreed to in the House, then discharged from a Senate committee
# and not agreed to in the Senate.
HCONRES89 = m(introduced="2026-04-23", committee="2026-09-24", passed_house="2026-07-23", failed_senate="2026-09-24")


def test_a_concurrent_resolution_has_one_step_per_chamber():
    path = vote_path(vote(bill_type="hconres", chamber="senate", date="2026-09-24",
                          question="On the Concurrent Resolution (H.Con.Res. 89)"), HCONRES89)
    assert path["track"] == "concurrent"
    assert steps(path) == [
        ("introduced", "Introduced", "done", "2026-04-23"),
        # The Senate committee's discharge doesn't date the House committee step.
        ("committee", "Committee", "done", None),
        ("passed_house", "Agreed to in House", "done", "2026-07-23"),
        ("passed_senate", "Not agreed to in Senate", "failed", "2026-09-24"),
    ]
    assert current(path) == ["passed_senate"]


def test_a_simple_resolution_has_only_its_own_chamber():
    path = vote_path(vote(bill_type="hres", date="2026-11-10", question="On Motion to Refer"), {})
    assert [(k, label, s) for k, label, s, _ in steps(path)] == [
        ("introduced", "Introduced", "done"), ("committee", "Committee", "upcoming"),
        ("passed_house", "Agreed to in House", "upcoming"),
    ]
    assert current(path) == ["passed_house"]


def test_a_senate_bill_starts_in_the_senate():
    path = vote_path(vote(bill_type="s", chamber="senate", question="On Passage of the Bill (S. 4668)"),
                     m(passed_senate="2026-09-28"))
    assert [s["key"] for s in path["steps"]][2:4] == ["passed_senate", "passed_house"]
    assert path["steps"][2]["anchor"] == "first-chamber"


def test_a_constitutional_amendment_stops_after_both_chambers():
    path = vote_path(vote(bill_type="hjres", title="Proposing an amendment to the Constitution of the United States"), {})
    assert path["track"] == "amendment"
    assert [s["key"] for s in path["steps"]] == ["introduced", "committee", "passed_house", "passed_senate"]


def test_a_vote_on_no_measure_has_no_path():
    assert vote_path(vote(bill_type=None), {}) is None


def test_a_vote_after_the_measure_became_law_is_placed_at_no_step():
    assert current(vote_path(vote(date="2025-08-01"), HR1)) == []
