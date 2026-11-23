"""Malformed floor data must warn, never fail the dbt build: the floor schedule is
secondary, and the hourly run stops before export and the bot if a test fails."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from yan.config import REPO_ROOT
from yan.stage import run as stage

HOUSE_ITEM = {
    "congress": "119", "week_date": "2026-11-09", "category": "Items that may be considered",
    "legis_num": "H.R. 1", "floor_text": "Example Act", "bill_type": "hr", "bill_number": "1",
}
MALFORMED = {
    "house_floor_items": [
        {**HOUSE_ITEM, "item_id": "--"},
        {**HOUSE_ITEM, "item_id": None},
        {**HOUSE_ITEM, "item_id": "7", "category": None, "floor_text": None, "bill_type": "zz"},
        {**HOUSE_ITEM, "item_id": "8", "congress": "next", "week_date": "Nov. 16", "category_order": "second"},
    ],
    "senate_floor_actions": [
        {"activity_date": "2026-11-10", "docnum": "--", "status_order": "0",
         "status_text": "Cloture motion presented in Senate."},
        {"activity_date": "11/12", "docnum": None, "status_order": "first", "status_text": None},
    ],
    "senate_session_days": [{"legislative_day": None, "convene_time": "noon", "next_convene_time": "later"}],
    "house_floor_days": [{"legislative_day": "Nov. 13", "convene_time": "10", "finished": "?"}],
}


@pytest.fixture
def run_results(monkeypatch, tmp_path):
    """dbt's results for the floor models and what they read, on a copy of the project
    whose staged tables are empty except for MALFORMED."""
    shutil.copytree(REPO_ROOT / "transform", tmp_path / "transform",
                    ignore=shutil.ignore_patterns("target", "logs", "dbt_packages"))
    monkeypatch.setattr(stage, "STAGED_DIR", tmp_path / "data" / "staged")
    for name in stage.SCHEMAS:
        stage.write(name, MALFORMED.get(name, []))
    dbt = subprocess.run(
        [str(Path(sys.executable).with_name("dbt")), "build", "--indirect-selection", "buildable",
         "--select", "+path:models/marts/floor", "+votes"],
        cwd=tmp_path / "transform", capture_output=True, text=True, timeout=120,
        env={**os.environ, "DBT_PROFILES_DIR": ".", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"},
    )
    assert dbt.returncode == 0, dbt.stdout + dbt.stderr
    results = json.loads((tmp_path / "transform" / "target" / "run_results.json").read_text())["results"]
    return {r["unique_id"]: r for r in results}


def test_malformed_floor_data_warns_and_never_fails_the_build(run_results):
    assert not [uid for uid, r in run_results.items() if r["status"] in ("error", "fail", "skipped")]
    warned = {uid for uid, r in run_results.items() if r["status"] == "warn"}
    assert any("not_null_floor_schedule_title" in uid for uid in warned)
    assert any("accepted_values_floor_schedule_bill_type" in uid for uid in warned)
    assert any("not_null_stg_floor__senate_session_days_convene_time_et" in uid for uid in warned)
    # The House IDs '--' and null, and the Senate docnum '--'.
    [ids] = [r for uid, r in run_results.items() if "floor_ids_have_letters_or_digits" in uid]
    assert (ids["status"], ids["failures"]) == ("warn", 3)
