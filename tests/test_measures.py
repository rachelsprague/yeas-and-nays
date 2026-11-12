import pytest

from yan.measures import bill_label, parse_measure
from yan.stage.run import with_bill


@pytest.mark.parametrize("recorded, expected", [
    ("H R 1013", ("hr", "1013")),
    ("H RES 1655", ("hres", "1655")),
    ("H J RES 7", ("hjres", "7")),
    ("H CON RES 14", ("hconres", "14")),
    ("H.R. 2347", ("hr", "2347")),
    ("S. 5", ("s", "5")),
    ("S 5", ("s", "5")),
    ("S.J.Res. 98", ("sjres", "98")),
    ("S.Con.Res. 7", ("sconres", "7")),
    ("S.Res. 412", ("sres", "412")),
])
def test_bills_and_resolutions(recorded, expected):
    assert parse_measure(recorded) == expected


@pytest.mark.parametrize("recorded", ["PN1129", "PN11-22", "QUORUM", "ADJOURN", "", None])
def test_nominations_and_non_measures_have_no_bill(recorded):
    assert parse_measure(recorded) is None


def test_stage_adds_bill_columns_and_keeps_the_recorded_measure():
    votes = with_bill([{"legis_num": "H RES 1655"}, {"legis_num": "QUORUM"}], "legis_num")
    assert votes == [
        {"legis_num": "H RES 1655", "bill_type": "hres", "bill_number": "1655"},
        {"legis_num": "QUORUM", "bill_type": None, "bill_number": None},
    ]


def test_bill_label_is_the_citation_form():
    assert bill_label("hres", "1655") == "H.Res. 1655"
    assert bill_label("sjres", "98") == "S.J.Res. 98"
    assert bill_label("hr", "1013") == "H.R. 1013"
