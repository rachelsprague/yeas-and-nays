import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "report_dbt_warnings.py"
spec = importlib.util.spec_from_file_location("report_dbt_warnings", SCRIPT)
rdw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rdw)


def result(unique_id, status, message=None):
    return {"unique_id": unique_id, "status": status, "message": message}


PASSED = result("test.yeas_and_nays.unique_votes_vote_id.0a1b2c", "pass")
BUILT = result("model.yeas_and_nays.votes", "success", "OK")
FAILED = result("test.yeas_and_nays.unique_bills_bill_id.3d4e5f", "fail", "Got 2 results")
SINGULAR = result("test.yeas_and_nays.positions_outside_member_term_dates", "warn",
                  "Got 49 results, configured to warn if != 0")
GENERIC = result("test.yeas_and_nays.not_null_votes_yeas_needed.6a7b8c", "warn",
                 "Got 1 result, configured to warn if != 0")


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Run the script over results; returns its output and the job summary."""
    def run(*results):
        path = tmp_path / "run_results.json"
        path.write_text(json.dumps({"results": results}))
        summary = tmp_path / "summary.md"
        summary.write_text("")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        rdw.main(str(path))
        return capsys.readouterr().out, summary.read_text()
    return run


def test_each_warned_test_is_annotated_and_listed(run):
    out, summary = run(PASSED, SINGULAR, BUILT, GENERIC, FAILED)
    assert out.splitlines() == [
        "::warning title=dbt test::not_null_votes_yeas_needed: Got 1 result, configured to warn if != 0",
        "::warning title=dbt test::positions_outside_member_term_dates: "
        "Got 49 results, configured to warn if != 0",
    ]
    assert summary == (
        "### dbt warnings\n\n"
        "- `not_null_votes_yeas_needed: Got 1 result, configured to warn if != 0`\n"
        "- `positions_outside_member_term_dates: Got 49 results, configured to warn if != 0`\n"
    )


def test_no_warnings_leaves_the_summary_empty(run):
    assert run(PASSED, BUILT, FAILED) == ("No dbt warnings.\n", "")


def test_a_message_stays_on_one_line(run):
    out, summary = run(result("test.yeas_and_nays.a", "warn", "100%\n::error::x"))
    assert out == "::warning title=dbt test::a: 100%25 ::error::x\n"
    assert summary.endswith("- `a: 100% ::error::x`\n")


def test_a_warning_with_no_message_is_still_listed(run):
    out, _ = run(result("test.yeas_and_nays.a", "warn"))
    assert out == "::warning title=dbt test::a: warned\n"


def test_no_summary_file_outside_actions(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = tmp_path / "run_results.json"
    path.write_text(json.dumps({"results": [GENERIC]}))
    rdw.main(str(path))
    assert "not_null_votes_yeas_needed" in capsys.readouterr().out
