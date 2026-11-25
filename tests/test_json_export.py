import datetime as dt
import json

from yan.export.json_export import (
    EASTERN,
    dumps,
    floor_schedule_document,
    members_as_of_vote,
    meta_document,
    summary_document,
    vote_document,
    with_bot_posts,
    with_measure_label,
)


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
    seats = {"A1": ("TX", 1), "A2": ("TX", 2), "A3": ("VT", 0)}
    for p in positions:
        p["chamber"] = "house"
        p["state"], p["district"] = seats[p["bioguide_id"]]
    members = {p["bioguide_id"]: p for p in positions}
    doc = vote_document({"vote_id": "h119-1-0001"}, positions, members)

    assert doc["against_party_majority"] == [{"bioguide_id": "A2", "member_label": "B (R-TX-2)", "position": "Nay"}]
    assert doc["party_totals"] == {"R": {"yes": 1, "no": 1}, "I": {"not_voting": 1}}
    assert doc["caucus_majority_position"] == {"R": "yes", "D": "no"}
    assert doc["positions"] == {"A1": "Yea", "A2": "Nay", "A3": "Not Voting"}
    assert doc["summary"] is None
    assert doc["members_as_of_vote"] == {}


def test_members_as_of_vote_lists_only_members_whose_party_or_seat_has_changed():
    def seat(chamber, state, district, party, caucus):
        return {"chamber": chamber, "state": state, "district": district, "party": party, "caucus_party": caucus}

    then = {
        "SAME": seat("house", "TX", 1, "R", "R"),
        "PARTY": seat("house", "CA", 3, "R", "R"),
        "CAUCUS": seat("house", "ME", 1, "I", "R"),
        "DISTRICT": seat("house", "CA", 9, "D", "D"),
        "CHAMBER": seat("house", "KY", 4, "R", "R"),
    }
    now = {
        **then,
        "PARTY": seat("house", "CA", 3, "I", "R"),
        "CAUCUS": seat("house", "ME", 1, "I", "D"),
        "DISTRICT": seat("house", "CA", 11, "D", "D"),
        "CHAMBER": seat("senate", "KY", None, "R", "R"),
    }
    positions = [{"bioguide_id": i, "position_raw": "Yea", **s} for i, s in then.items()]
    assert members_as_of_vote(positions, now) == {i: s for i, s in then.items() if i != "SAME"}


def test_meta_tracks_latest_roll_per_chamber_and_session():
    votes = [
        {"chamber": "house", "congress": 119, "session": 1, "roll_number": 362, "vote_date": dt.date(2025, 12, 18)},
        {"chamber": "house", "congress": 119, "session": 2, "roll_number": 5, "vote_date": dt.date(2026, 1, 7)},
        {"chamber": "senate", "congress": 119, "session": 1, "roll_number": 659, "vote_date": dt.date(2025, 12, 18)},
    ]
    meta = meta_document(votes, members=[{}, {}])
    assert meta["latest_roll_number"] == {"house": {"119": {"1": 362, "2": 5}}, "senate": {"119": {"1": 659}}}
    assert meta["latest_vote_date"] == dt.date(2026, 1, 7)
    assert meta["member_count"] == 2


def test_meta_keeps_each_congress_roll_numbers_apart():
    votes = [
        {"chamber": "house", "congress": 119, "session": 1, "roll_number": 362, "vote_date": dt.date(2025, 12, 18)},
        {"chamber": "house", "congress": 120, "session": 1, "roll_number": 4, "vote_date": dt.date(2027, 1, 7)},
    ]
    assert meta_document(votes, members=[])["latest_roll_number"] == {"house": {"119": {"1": 362}, "120": {"1": 4}}}


def test_votes_carry_measure_number_in_citation_form():
    assert with_measure_label({"chamber": "house", "measure_number": "H RES 1655"})["measure_label"] == "H.Res. 1655"
    assert with_measure_label({"chamber": "senate", "measure_number": "PN1129"})["measure_label"] == "PN1129"
    assert with_measure_label({"chamber": "house", "measure_number": None})["measure_label"] is None


def test_votes_carry_whether_the_bot_posts_them():
    passage = {"chamber": "house", "question": "On Passage", "measure_number": "H R 2102",
               "measure_title": "Major Richard Star Act", "result": "Passed", "yea_count": 392}
    rule = {**passage, "question": "On Agreeing to the Resolution", "measure_number": "H RES 1247",
            "measure_title": "Providing for consideration of the bill (H.R. 2102)"}
    assert with_bot_posts(passage)["bot_posts"] is True
    assert with_bot_posts(rule)["bot_posts"] is False


def test_summary_carries_the_version_it_describes():
    summary = {"summary_html": "<p>This bill&nbsp;allows X.</p>", "action_desc": "Introduced in House",
               "action_date": dt.date(2025, 2, 5), "version_code": "00"}
    assert summary_document(summary) == {
        "html": "<p>This bill allows X.</p>", "version": "Introduced in House",
        "version_date": dt.date(2025, 2, 5), "version_code": "00",
    }
    assert summary_document(None) is None


def _warehouse(path, sponsored_rows, cosponsored_rows=(), cosponsored_lists=(), sponsored_lists=()):
    """A minimal warehouse with the tables run() reads: two members, one vote."""
    import duckdb

    con = duckdb.connect(str(path))
    con.execute("""create table members as select * from (values
                   ('A000001', 120, 'house', 'TX', 2, 'R', 'R'), ('B000002', 119, 'house', 'TX', 3, 'R', 'R'))
                   t(bioguide_id, last_congress, chamber, state, district, party, caucus_party)""")
    con.execute("""create table member_congresses as select * from (values
                   ('A000001', 119, true, date '2025-01-03', date '2027-01-03', 10),
                   ('A000001', 120, true, date '2027-01-03', date '2029-01-03', 1),
                   ('B000002', 119, true, date '2025-01-03', date '2025-06-01', null))
                   t(bioguide_id, congress, served_in_congress, served_from, served_to, votes_cast)""")
    con.execute("""create table votes as select 'h119-1-0001' as vote_id, 'house' as chamber, 1 as session,
                   1 as roll_number, date '2025-01-03' as vote_date, timestamp '2025-01-03 12:00' as vote_time_et,
                   'H R 1' as measure_number, 'On Passage' as question, 'Passed' as result,
                   1 as yea_count, 119 as congress, 'hr' as bill_type, '1' as bill_number,
                   'An Act' as measure_title""")
    con.execute("""create table bill_milestones as select 119 as congress, 'hr' as bill_type, '1' as bill_number,
                   'passed_house' as milestone, date '2025-01-03' as first_date, date '2025-01-03' as last_date""")
    con.execute("""create table positions as select 'h119-1-0001' as vote_id, 'A000001' as bioguide_id,
                   'A (R-TX-1)' as member_label, 'house' as chamber, 'TX' as state, 1 as district,
                   'R' as party, 'R' as caucus_party, 'Yea' as position_raw,
                   'yes' as position, 'yes' as caucus_majority_position, false as voted_against_party_majority""")
    for table, rows in (("sponsored_bills", sponsored_rows), ("cosponsored_bills", cosponsored_rows)):
        con.execute(f"""create table {table} (bioguide_id varchar, congress varchar, bill_id varchar, bill_type varchar,
                       bill_number varchar, title varchar, introduced_date date, latest_action_date date,
                       latest_action_text varchar, policy_area varchar, congress_gov_url varchar,
                       latest_vote_id varchar)""")
        for row in rows:
            con.execute(f"insert into {table} (bioguide_id, congress, bill_type, bill_number, introduced_date) "
                        "values (?, ?, ?, ?, ?)", row if len(row) == 5 else (row[0], "120", *row[1:]))
    for table, ids in (("sponsored_lists", sponsored_lists), ("cosponsored_lists", cosponsored_lists)):
        con.execute(f"create table {table} (bioguide_id varchar, congress integer, bill_count integer)")
        for bioguide_id in ids:
            # A bare ID is a list fetched for the 120th; (ID, congress) names the Congress.
            bioguide_id, congress = (bioguide_id, 120) if isinstance(bioguide_id, str) else bioguide_id
            con.execute(f"insert into {table} values (?, ?, 0)", [bioguide_id, congress])
    con.execute("""create table vote_summaries (vote_id varchar, version_code varchar, action_date date,
                   action_desc varchar, summary_html varchar)""")
    con.execute("""create table floor_schedule (chamber varchar, item_id varchar, week_date date, filed_date date,
                   category varchar, category_order integer, item_order integer, question varchar,
                   measure_number varchar, bill_type varchar, bill_number varchar, title varchar,
                   amends varchar, congress_gov_url varchar, vote_id varchar, decided_date date,
                   decided_question varchar, decided_outcome varchar)""")
    con.execute("""create table senate_sessions (convene_time_et timestamp, adjourn_time_et timestamp,
                   next_convene_time_et timestamp, next_convene_pro_forma boolean)""")
    con.execute("""create table house_floor_days (legislative_day date, convene_time_et timestamp,
                   adjourned boolean, next_convene_time_et timestamp)""")
    con.execute("""create table member_bios as select 'A000001' as bioguide_id, 'CDIR-2026-02-20' as edition,
                   date '2026-02-20' as date_issued, 'of Town, AL; born in Town, AL' as opening,
                   'B.A., Example College' as education, 'teacher' as professional_history,
                   null::varchar as military_service""")
    con.close()


def test_run_writes_one_file_per_member_with_their_bills_newest_first(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [
        ("A000001", "hr", "9", dt.date(2025, 3, 1)),
        ("A000001", "hr", "10", dt.date(2025, 3, 1)),
        ("A000001", "hres", "2", dt.date(2025, 5, 1)),
    ], sponsored_lists=["A000001"])
    out = tmp_path / "out"
    (out / "members").mkdir(parents=True)
    (out / "members" / "Z000009.json").write_text("{}")  # member no longer in the warehouse

    run(warehouse, out)

    a = json.loads((out / "members" / "A000001.json").read_text())
    assert [g["congress"] for g in a["sponsored"]] == [120]
    assert [b["measure_label"] for b in a["sponsored"][0]["bills"]] == ["H.Res. 2", "H.R. 10", "H.R. 9"]
    assert a["bio"] == {
        "edition": "CDIR-2026-02-20", "date_issued": "2026-02-20", "opening": "of Town, AL; born in Town, AL",
        "education": "B.A., Example College", "professional_history": "teacher", "military_service": None,
    }
    assert json.loads((out / "members" / "B000002.json").read_text()) == {
        "bioguide_id": "B000002", "sponsored": None, "cosponsored": None, "bio": None,
    }
    assert sorted(p.name for p in (out / "members").iterdir()) == ["A000001.json", "B000002.json"]
    assert json.loads((out / "meta.json").read_text())["has_sponsored_bills"] is True


def test_run_groups_a_member_bills_by_congress_newest_first(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [
        ("A000001", "119", "hr", "9", dt.date(2025, 3, 1)),
        ("A000001", "120", "hr", "9", dt.date(2027, 3, 1)),
    ], sponsored_lists=[("A000001", 119), ("A000001", 120)])
    out = tmp_path / "out"
    run(warehouse, out)

    a = json.loads((out / "members" / "A000001.json").read_text())
    assert [(g["congress"], [b["introduced_date"] for b in g["bills"]]) for g in a["sponsored"]] == [
        (120, ["2027-03-01"]), (119, ["2025-03-01"])]


def test_run_gives_each_member_stats_for_their_last_congress_and_every_congress(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    out = tmp_path / "out"
    run(warehouse, out)

    members = {m["bioguide_id"]: m for m in json.loads((out / "members.json").read_text())["members"]}
    a = members["A000001"]
    assert a["votes_cast"] == 1  # the 120th's, not the 119th's
    assert [(c["congress"], c["served_from"], c["votes_cast"]) for c in a["congresses"]] == [
        (120, "2027-01-03", 1), (119, "2025-01-03", 10)]
    assert members["B000002"]["votes_cast"] is None
    assert [c["congress"] for c in members["B000002"]["congresses"]] == [119]


def test_run_leaves_stats_null_when_the_last_congress_has_none(tmp_path):
    """A returning member before their chamber's first roll call of the new Congress:
    a row for their last Congress with no stats, or no row at all. Earlier Congresses keep theirs."""
    import duckdb

    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    con = duckdb.connect(str(warehouse))
    con.execute("update members set last_congress = 120 where bioguide_id = 'B000002'")
    con.execute("""insert into member_congresses values
                   ('A000001', 121, true, date '2029-01-03', date '2031-01-03', null)""")
    con.execute("update members set last_congress = 121 where bioguide_id = 'A000001'")
    con.close()
    out = tmp_path / "out"
    run(warehouse, out)

    members = {m["bioguide_id"]: m for m in json.loads((out / "members.json").read_text())["members"]}
    a, b = members["A000001"], members["B000002"]
    assert a["votes_cast"] is None
    assert [(c["congress"], c["votes_cast"]) for c in a["congresses"]] == [(121, None), (120, 1), (119, 10)]
    # No row for the last Congress at all: still exported, stats null.
    assert b["last_congress"] == 120 and b["votes_cast"] is None
    assert [c["congress"] for c in b["congresses"]] == [119]


def test_run_writes_each_vote_with_its_measures_path(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    out = tmp_path / "out"
    run(warehouse, out)

    doc = json.loads((out / "votes" / "h119-1-0001.json").read_text())
    # The fixture's member now holds TX-2.
    assert doc["members_as_of_vote"] == {
        "A000001": {"chamber": "house", "state": "TX", "district": 1, "party": "R", "caucus_party": "R"}}
    path = doc["path"]
    assert path["track"] == "law"
    passed = next(s for s in path["steps"] if s["key"] == "passed_house")
    assert passed == {"key": "passed_house", "label": "Passed House", "date": "2025-01-03", "status": "done",
                      "anchor": "first-chamber", "current": True}


def test_run_writes_nothing_when_a_past_congress_vote_is_missing(tmp_path):
    import pytest

    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    out = tmp_path / "out"
    out.mkdir()
    before = json.dumps({"congress": 118, "votes": [{"vote_id": "h118-2-0500", "congress": 118}]})
    (out / "votes.json").write_text(before)

    with pytest.raises(RuntimeError, match="h118-2-0500"):
        run(warehouse, out)
    assert [p.name for p in out.iterdir()] == ["votes.json"]
    assert (out / "votes.json").read_text() == before


def test_run_writes_cosponsored_bills_and_null_until_a_list_is_fetched(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [],
               cosponsored_rows=[("A000001", "s", "7", dt.date(2025, 2, 1)),
                                 ("A000001", "sres", "3", dt.date(2025, 4, 1))],
               cosponsored_lists=["A000001"])
    out = tmp_path / "out"
    run(warehouse, out)

    a = json.loads((out / "members" / "A000001.json").read_text())
    assert [b["measure_label"] for b in a["cosponsored"][0]["bills"]] == ["S.Res. 3", "S. 7"]
    # B000002's list hasn't been fetched yet: null, not an empty list.
    assert json.loads((out / "members" / "B000002.json").read_text())["cosponsored"] is None


def test_run_writes_an_empty_cosponsored_list_once_fetched(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [], cosponsored_lists=["B000002"])
    run(warehouse, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "members" / "B000002.json").read_text())["cosponsored"] == [
        {"congress": 120, "bills": []}]


def test_run_writes_an_empty_sponsored_list_once_fetched(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [], sponsored_lists=["B000002"])
    run(warehouse, tmp_path / "out")
    # B000002's list was fetched and is empty; A000001's wasn't (a failed fetch): null.
    assert json.loads((tmp_path / "out" / "members" / "B000002.json").read_text())["sponsored"] == [
        {"congress": 120, "bills": []}]
    assert json.loads((tmp_path / "out" / "members" / "A000001.json").read_text())["sponsored"] is None
    # A fetched list counts even with no bills on it, so the section shows "none".
    assert json.loads((tmp_path / "out" / "meta.json").read_text())["has_sponsored_bills"] is True


def test_run_flags_missing_sponsored_lists(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    run(warehouse, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "meta.json").read_text())["has_sponsored_bills"] is False


def test_run_writes_the_floor_schedule_in_numeric_order(tmp_path):
    import duckdb

    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    con = duckdb.connect(str(warehouse))
    for measure in ("PN1272-13", "PN1272-3", "H.R. 2347"):
        con.execute("""insert into floor_schedule (chamber, item_id, filed_date, question, measure_number, title)
                       values ('senate', 's-' || ?, date '2026-11-11', 'On the Cloture Motion', ?, 'T')""",
                    [measure, measure])
    con.execute("""insert into floor_schedule (chamber, item_id, filed_date, question, measure_number, title, amends)
                   values ('senate', 's-none', date '2026-11-11', 'On the Cloture Motion', null, 'T', 'H.R. 2347')""")
    con.execute("""insert into floor_schedule (chamber, item_id, week_date, measure_number, title, decided_date,
                   decided_question, decided_outcome)
                   values ('house', 'h-1', date '2026-11-09', 'H.R. 5', 'T', date '2026-11-10', 'On passage',
                           'Passed by voice vote')""")
    con.execute("insert into senate_sessions values ('2026-11-12 12:00', '2026-11-12 16:52', '2026-11-16 15:00', false)")
    con.execute("insert into house_floor_days values ('2026-11-17', '2026-11-17 12:00:04', false, null)")
    con.close()

    run(warehouse, tmp_path / "out")

    doc = json.loads((tmp_path / "out" / "floor_schedule.json").read_text())
    # An item with no number sorts last.
    assert [i["measure_label"] for i in doc["items"]] == [
        "H.R. 5", "H.R. 2347", "PN1272-3", "PN1272-13", "Amendment to H.R. 2347",
    ]
    decided = [(i["decided_date"], i["decided_question"], i["decided_outcome"]) for i in doc["items"]]
    assert decided == [("2026-11-10", "On passage", "Passed by voice vote")] + [(None, None, None)] * 4
    assert doc["senate_next_convene_et"] == "2026-11-16T15:00:00"
    assert doc["floor_status"] == {
        "house": {"convened_at": "2026-11-17T12:00:04-05:00", "next_convene_at": None, "next_convene_pro_forma": None},
        "senate": {"convened_at": None, "next_convene_at": "2026-11-16T15:00:00-05:00", "next_convene_pro_forma": False},
    }


def test_floor_schedule_labels_items_and_takes_the_latest_next_convene():
    items = [
        {"measure_number": "H. Res. 1650", "bill_type": "hres", "bill_number": "1650", "amends": None},
        {"measure_number": "PN1272-3", "bill_type": None, "bill_number": None, "amends": None},
        {"measure_number": "S.Amdt. 6883", "bill_type": None, "bill_number": None, "amends": "H.R. 2347"},
        {"measure_number": "H. Res. ___", "bill_type": None, "bill_number": None, "amends": None},
    ]
    sessions = [
        {"next_convene_time_et": dt.datetime(2026, 11, 12, 12)},
        {"next_convene_time_et": dt.datetime(2026, 11, 16, 15)},
    ]
    doc = floor_schedule_document(items, sessions, [])
    assert [i["measure_label"] for i in doc["items"]] == [
        "H.Res. 1650", "PN1272-3", "S.Amdt. 6883 to H.R. 2347", "H. Res. ___",
    ]
    assert doc["senate_next_convene_et"] == dt.datetime(2026, 11, 16, 15)
    assert floor_schedule_document([], [], [])["senate_next_convene_et"] is None


def test_floor_schedule_item_with_no_measure_number():
    items = [
        {"measure_number": None, "bill_type": None, "bill_number": None, "amends": None},
        {"measure_number": None, "bill_type": None, "bill_number": None, "amends": "H.R. 2347"},
        {"measure_number": "", "bill_type": None, "bill_number": None, "amends": None},
        {"measure_number": "", "bill_type": None, "bill_number": None, "amends": "H.R. 2347"},
    ]
    doc = floor_schedule_document(items, [], [])
    assert [i["measure_label"] for i in doc["items"]] == [
        None, "Amendment to H.R. 2347", None, "Amendment to H.R. 2347",
    ]


def test_floor_status_is_in_session_until_adjourned_then_the_next_convening():
    convened = {"convene_time_et": dt.datetime(2026, 11, 16, 15), "adjourn_time_et": None,
                "next_convene_time_et": None, "next_convene_pro_forma": None}
    adjourned = {"convene_time_et": dt.datetime(2026, 11, 16, 15), "adjourn_time_et": dt.datetime(2026, 11, 16, 19, 2),
                 "next_convene_time_et": dt.datetime(2026, 11, 17, 10), "next_convene_pro_forma": True}
    house_in = {"convene_time_et": dt.datetime(2026, 11, 17, 12), "adjourned": False,
                "next_convene_time_et": None}
    house_out = {"convene_time_et": dt.datetime(2026, 11, 13, 10), "adjourned": True,
                 "next_convene_time_et": dt.datetime(2026, 11, 17, 12)}

    status = floor_schedule_document([], [convened], [house_in])["floor_status"]
    assert status["senate"]["convened_at"] == dt.datetime(2026, 11, 16, 15, tzinfo=EASTERN)
    assert status["senate"]["next_convene_at"] is None
    assert status["house"]["convened_at"] == dt.datetime(2026, 11, 17, 12, tzinfo=EASTERN)
    assert status["house"]["next_convene_at"] is None

    status = floor_schedule_document([], [adjourned], [house_out])["floor_status"]
    assert status["senate"] == {"convened_at": None, "next_convene_at": dt.datetime(2026, 11, 17, 10, tzinfo=EASTERN),
                                "next_convene_pro_forma": True}
    assert status["house"] == {"convened_at": None, "next_convene_at": dt.datetime(2026, 11, 17, 12, tzinfo=EASTERN),
                               "next_convene_pro_forma": None}

    # A session under way that the row before flagged as pro forma isn't listed as convened.
    status = floor_schedule_document([], [adjourned, convened], [])["floor_status"]
    assert status["senate"]["convened_at"] is None
    not_pro_forma = {**adjourned, "next_convene_pro_forma": False}
    status = floor_schedule_document([], [not_pro_forma, convened], [])["floor_status"]
    assert status["senate"]["convened_at"] == dt.datetime(2026, 11, 16, 15, tzinfo=EASTERN)

    # Before any data.
    empty = {"convened_at": None, "next_convene_at": None, "next_convene_pro_forma": None}
    assert floor_schedule_document([], [], [])["floor_status"] == {"house": empty, "senate": empty}


def test_floor_status_times_carry_the_eastern_offset_in_summer_too():
    sessions = [{"convene_time_et": dt.datetime(2026, 7, 1, 10), "adjourn_time_et": dt.datetime(2026, 7, 1, 18),
                 "next_convene_time_et": dt.datetime(2026, 7, 2, 10), "next_convene_pro_forma": False}]
    doc = json.loads(dumps(floor_schedule_document([], sessions, [])))
    assert doc["floor_status"]["senate"]["next_convene_at"] == "2026-07-02T10:00:00-04:00"
