import datetime as dt
import json

from yan.export.json_export import (
    dumps,
    floor_schedule_document,
    meta_document,
    summary_document,
    vote_document,
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


def _warehouse(path, sponsored_rows, cosponsored_rows=(), cosponsored_lists=()):
    """A minimal warehouse with the tables run() reads: two members, one vote."""
    import duckdb

    con = duckdb.connect(str(path))
    con.execute("create table members as select * from (values ('A000001'), ('B000002')) t(bioguide_id)")
    con.execute("create table member_stats as select 'A000001' as bioguide_id, 1 as votes_cast")
    con.execute("""create table votes as select 'h119-1-0001' as vote_id, 'house' as chamber, 1 as session,
                   1 as roll_number, date '2025-01-03' as vote_date, timestamp '2025-01-03 12:00' as vote_time_et,
                   'H R 1' as measure_number""")
    con.execute("""create table positions as select 'h119-1-0001' as vote_id, 'A000001' as bioguide_id,
                   'A (R-TX-1)' as member_label, 'R' as party, 'R' as caucus_party, 'Yea' as position_raw,
                   'yes' as position, 'yes' as caucus_majority_position, false as voted_against_party_majority""")
    for table, rows in (("sponsored_bills", sponsored_rows), ("cosponsored_bills", cosponsored_rows)):
        con.execute(f"""create table {table} (bioguide_id varchar, bill_id varchar, bill_type varchar,
                       bill_number varchar, title varchar, introduced_date date, latest_action_date date,
                       latest_action_text varchar, policy_area varchar, congress_gov_url varchar,
                       latest_vote_id varchar)""")
        for row in rows:
            con.execute(f"insert into {table} (bioguide_id, bill_type, bill_number, introduced_date) "
                        "values (?, ?, ?, ?)", row)
    con.execute("create table cosponsored_lists (bioguide_id varchar, congress integer, bill_count integer)")
    for bioguide_id in cosponsored_lists:
        con.execute("insert into cosponsored_lists values (?, 119, 0)", [bioguide_id])
    con.execute("""create table vote_summaries (vote_id varchar, version_code varchar, action_date date,
                   action_desc varchar, summary_html varchar)""")
    con.execute("""create table floor_schedule (chamber varchar, item_id varchar, week_date date, filed_date date,
                   category varchar, category_order integer, item_order integer, question varchar,
                   measure_number varchar, bill_type varchar, bill_number varchar, title varchar,
                   amends varchar, congress_gov_url varchar, vote_id varchar)""")
    con.execute("""create table senate_sessions (convene_time_et timestamp, adjourn_time_et timestamp,
                   next_convene_time_et timestamp)""")
    con.close()


def test_run_writes_one_file_per_member_with_their_bills_newest_first(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [
        ("A000001", "hr", "9", dt.date(2025, 3, 1)),
        ("A000001", "hr", "10", dt.date(2025, 3, 1)),
        ("A000001", "hres", "2", dt.date(2025, 5, 1)),
    ])
    out = tmp_path / "out"
    (out / "members").mkdir(parents=True)
    (out / "members" / "Z000009.json").write_text("{}")  # member no longer in the warehouse

    run(warehouse, out)

    a = json.loads((out / "members" / "A000001.json").read_text())
    assert [b["measure_label"] for b in a["sponsored"]] == ["H.Res. 2", "H.R. 10", "H.R. 9"]
    assert json.loads((out / "members" / "B000002.json").read_text()) == {
        "bioguide_id": "B000002", "sponsored": [], "cosponsored": None,
    }
    assert sorted(p.name for p in (out / "members").iterdir()) == ["A000001.json", "B000002.json"]
    assert json.loads((out / "meta.json").read_text())["has_sponsored_bills"] is True


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
    assert [b["measure_label"] for b in a["cosponsored"]] == ["S.Res. 3", "S. 7"]
    # B000002's list hasn't been fetched yet: null, not an empty list.
    assert json.loads((out / "members" / "B000002.json").read_text())["cosponsored"] is None


def test_run_writes_an_empty_cosponsored_list_once_fetched(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [], cosponsored_lists=["B000002"])
    run(warehouse, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "members" / "B000002.json").read_text())["cosponsored"] == []


def test_run_flags_missing_sponsored_lists(tmp_path):
    from yan.export.json_export import run

    warehouse = tmp_path / "warehouse.duckdb"
    _warehouse(warehouse, [])
    run(warehouse, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "meta.json").read_text())["has_sponsored_bills"] is False


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
    doc = floor_schedule_document(items, sessions)
    assert [i["measure_label"] for i in doc["items"]] == [
        "H.Res. 1650", "PN1272-3", "S.Amdt. 6883 to H.R. 2347", "H. Res. ___",
    ]
    assert doc["senate_next_convene_et"] == dt.datetime(2026, 11, 16, 15)
    assert floor_schedule_document([], [])["senate_next_convene_et"] is None
