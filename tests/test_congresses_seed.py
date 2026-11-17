"""The dbt project's list of Congresses and its Congress in session match yan.config."""

import csv
import datetime as dt
import re

from yan.config import CONGRESS, CONGRESSES, REPO_ROOT

TRANSFORM = REPO_ROOT / "transform"


def test_congresses_seed_matches_config():
    with open(TRANSFORM / "seeds" / "congresses.csv", newline="") as f:
        rows = {int(r["congress"]): (r["start_date"], r["end_date"]) for r in csv.DictReader(f)}
    # A Congress runs from Jan. 3 of its first session's year to Jan. 3 after its last.
    assert rows == {
        congress: (dt.date(sessions[1], 1, 3).isoformat(), dt.date(max(sessions.values()) + 1, 1, 3).isoformat())
        for congress, sessions in CONGRESSES.items()
    }


def test_dbt_congress_var_is_the_one_in_session():
    project = (TRANSFORM / "dbt_project.yml").read_text()
    assert re.search(r"^\s+congress: (\d+)$", project, re.M).group(1) == str(CONGRESS)
