import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_zip_lookup.py"
spec = importlib.util.spec_from_file_location("build_zip_lookup", SCRIPT)
zl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zl)


def block(geoid, cd):
    return {"GEOID": geoid, "CDFP": cd}


def zcta_block(zcta, geoid, land=100):
    return {"GEOID_ZCTA5_20": zcta, "GEOID_TABBLOCK_20": geoid, "AREALAND_PART": str(land)}


# seat, block_seats

def test_seat_matches_the_site_seat_key():
    assert zl.seat("21", "06") == "KY-6"
    assert zl.seat("56", "00") == "WY"


def test_seat_is_none_where_no_member_votes():
    assert zl.seat("11", "98") is None  # DC
    assert zl.seat("72", "98") is None  # Puerto Rico
    assert zl.seat("72", "00") is None  # a territory, whatever its code


def test_block_seats_drops_blocks_with_no_district():
    seats = zl.block_seats([block("210010001001000", "01"), block("210010001001001", "ZZ"),
                            block("110010001001000", "98")])
    assert seats == {210010001001000: "KY-1", 110010001001000: None}


# zcta_seats

def test_zcta_seats_lists_every_district_a_zcta_has_land_in():
    blocks = {1: "KY-1", 2: "KY-2", 3: "KY-2"}
    rows = [zcta_block("40001", "1"), zcta_block("40001", "2"), zcta_block("40002", "3")]
    assert zl.zcta_seats(rows, blocks) == {"40001": {"KY-1", "KY-2"}, "40002": {"KY-2"}}


def test_zcta_seats_ignores_water_and_blocks_outside_any_zcta():
    blocks = {1: "KY-1", 2: "KY-2"}
    rows = [zcta_block("40001", "1"), zcta_block("40001", "2", land=0), zcta_block("", "2")]
    assert zl.zcta_seats(rows, blocks) == {"40001": {"KY-1"}}


def test_zcta_seats_keeps_a_zcta_where_no_member_votes_with_no_seats():
    blocks = {1: None, 2: "MD-4"}
    rows = [zcta_block("20001", "1"), zcta_block("20002", "1"), zcta_block("20002", "2")]
    assert zl.zcta_seats(rows, blocks) == {"20001": set(), "20002": {"MD-4"}}


def test_zcta_seats_skips_a_block_with_no_district():
    assert zl.zcta_seats([zcta_block("40001", "9")], {}) == {"40001": set()}


# official_seats, differences, map_problems

def test_official_seats_reads_a_census_relationship_file_by_land():
    rows = [{"GEOID_CD119_20": "2101", "GEOID_ZCTA5_20": "40001", "AREALAND_PART": "5"},
            {"GEOID_CD119_20": "2102", "GEOID_ZCTA5_20": "40001", "AREALAND_PART": "0"},
            {"GEOID_CD119_20": "2102", "GEOID_ZCTA5_20": "", "AREALAND_PART": "5"},
            {"GEOID_CD119_20": "1198", "GEOID_ZCTA5_20": "20001", "AREALAND_PART": "5"}]
    assert zl.official_seats(rows) == {"40001": {"KY-1"}, "20001": set()}


def test_differences_names_each_mismatched_zcta_up_to_a_limit():
    ours = {f"4000{i}": {"KY-1"} for i in range(5)}
    official = {f"4000{i}": {"KY-2"} for i in range(5)} | {"40009": {"KY-1"}}
    out = zl.differences(ours, official, limit=2)
    assert out == ["40000: ['KY-1'] vs ['KY-2']", "40001: ['KY-1'] vs ['KY-2']", "... and 4 more"]
    assert zl.differences(ours, ours) == []


def test_map_problems_names_seats_on_only_one_side():
    lookup = {"40001": {"KY-1", "KY-7"}, "20001": set()}
    assert zl.map_problems(lookup, {"KY-1", "KY-2"}) == ["not on the map: KY-7", "no ZCTA: KY-2"]
    assert zl.map_problems(lookup, {"KY-1", "KY-7"}) == []


# document

def test_document_lists_each_seats_zctas_in_district_order():
    lookup = {"40002": {"KY-10"}, "40001": {"KY-2", "KY-10"}, "82001": {"WY"}, "20001": set()}
    assert zl.document(120, lookup) == {
        "congress": 120,
        "districts": {"KY-2": "40001", "KY-10": "40001 40002", "WY": "82001"},
        "no_voting_member": "20001",
    }


# The committed lookups

@pytest.mark.parametrize("path", sorted((ROOT / "site" / "assets" / "maps").glob("zip-*.json")), ids=lambda p: p.name)
def test_committed_lookup_covers_exactly_its_maps_districts(path):
    doc = json.loads(path.read_text())
    drawn = json.loads((ROOT / "site" / "_maps" / f"{doc['congress']}.json").read_text())["districts"]
    assert set(doc["districts"]) == {f"{d['state']}-{d['district']}" if d["district"] else d["state"] for d in drawn}
    zctas = [z for zs in doc["districts"].values() for z in zs.split()] + doc["no_voting_member"].split()
    assert all(len(z) == 5 and z.isdigit() for z in zctas)
