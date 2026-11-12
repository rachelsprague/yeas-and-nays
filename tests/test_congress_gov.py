import datetime as dt
import os

from yan.ingest.congress_gov import needs_fetch

TODAY = dt.date(2026, 11, 12)


def test_fetches_missing_files(tmp_path):
    assert needs_fetch(tmp_path / "hr1.json", last_vote=dt.date(2025, 3, 1), today=TODAY)


def test_refetches_bills_voted_on_recently_and_stale_files(tmp_path):
    path = tmp_path / "hr1.json"
    path.write_text("{}")
    assert needs_fetch(path, last_vote=TODAY - dt.timedelta(days=2), today=TODAY)
    assert not needs_fetch(path, last_vote=dt.date(2025, 3, 1), today=TODAY)

    week_old = path.stat().st_mtime - 8 * 24 * 3600
    os.utime(path, (week_old, week_old))
    assert needs_fetch(path, last_vote=dt.date(2025, 3, 1), today=TODAY)
