import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_data_artifact.py"
spec = importlib.util.spec_from_file_location("check_data_artifact", SCRIPT)
cda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cda)


def state(house, senate):
    return {"house": {"last_vote_id": house}, "senate": {"last_vote_id": senate}}


@pytest.fixture
def committed(tmp_path):
    path = tmp_path / "committed_state.json"
    path.write_text(json.dumps(state("h119-2-0323", "s119-2-0262")))
    return path


@pytest.fixture
def artifact(tmp_path):
    """An artifact shaped like the update job's: out/ and bot/state.json."""
    root = tmp_path / "data"
    (root / "out" / "votes").mkdir(parents=True)
    (root / "out" / "members").mkdir()
    (root / "bot").mkdir()
    (root / "out" / "votes.json").write_text('{"votes": []}')
    (root / "out" / "floor_schedule.json").write_text('{"items": []}')
    (root / "out" / "votes" / "h119-2-0324.json").write_text("{}")
    (root / "out" / "votes" / "s120-1-0001.json").write_text("{}")
    (root / "out" / "members" / "A000055.json").write_text("{}")
    (root / "bot" / "state.json").write_text(json.dumps(state("h119-2-0324", "s119-2-0262")))
    return root


def test_an_artifact_like_exports_passes(artifact, committed):
    assert cda.check(artifact, committed) == []


def test_state_with_no_change_or_from_null_passes(artifact, committed, tmp_path):
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h119-2-0323", "s119-2-0262")))
    assert cda.check(artifact, committed) == []
    committed.write_text(json.dumps(state(None, None)))
    assert cda.check(artifact, committed) == []
    # No committed state yet (a fresh repo): anything well formed passes.
    assert cda.check(artifact, tmp_path / "missing.json") == []


@pytest.mark.parametrize("house, senate, expected", [
    ("h119-2-0322", "s119-2-0262", "house last_vote_id goes back from h119-2-0323 to h119-2-0322"),
    # Numeric order, not string order: session 1 of the 119th is before session 2.
    ("h119-1-0999", "s119-2-0262", "house last_vote_id goes back from h119-2-0323 to h119-1-0999"),
    ("h119-2-0323", None, "senate last_vote_id goes back from s119-2-0262 to None"),
])
def test_state_that_moves_backwards_fails(artifact, committed, house, senate, expected):
    (artifact / "bot" / "state.json").write_text(json.dumps(state(house, senate)))
    assert cda.check(artifact, committed) == [f"state.json: {expected}"]


def test_a_new_congress_counts_as_later(artifact, committed):
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h120-1-0001", "s120-1-0001")))
    assert cda.check(artifact, committed) == []


@pytest.mark.parametrize("doc, expected", [
    ("not json", "can't be read"),
    ([], "keys must be exactly house, senate"),
    ({"house": {"last_vote_id": None}}, "keys must be exactly house, senate"),
    ({**state(None, None), "extra": {}}, "keys must be exactly house, senate"),
    ({"house": "h119-2-0324", "senate": {"last_vote_id": None}}, 'house must be {"last_vote_id": ...}'),
    ({"house": {"last_vote_id": None, "x": 1}, "senate": {"last_vote_id": None}}, 'house must be {"last_vote_id": ...}'),
    (state("s119-2-0300", None), "house last_vote_id 's119-2-0300' isn't a house vote ID"),
    (state("h119-2-0324", 262), "senate last_vote_id 262 isn't a senate vote ID"),
    (state("h119-2-0324; rm", None), "isn't a house vote ID"),
])
def test_malformed_state_fails(artifact, committed, doc, expected):
    path = artifact / "bot" / "state.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    [problem] = cda.check(artifact, committed)
    assert problem.startswith("state.json: ") and expected in problem


@pytest.mark.parametrize("rel", [
    "out/.gitattributes",
    "out/votes/h119-2-0324.json.bak",
    "out/votes/evil.json",
    "out/members/a000056.json",
    "out/index.html",
    "out/Meta.json",
    "bot/other.json",
    "README.md",
])
def test_unexpected_files_fail(artifact, committed, rel):
    path = artifact / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    assert cda.check(artifact, committed) == [f"{rel!r}: unexpected file"]


@pytest.mark.parametrize("rel", ["out/extra", ".github", "bot/nested"])
def test_unexpected_directories_fail(artifact, committed, rel):
    (artifact / rel).mkdir()
    assert cda.check(artifact, committed) == [f"{rel!r}: unexpected directory"]


def test_symlinks_fail_even_with_an_allowed_name(artifact, committed, tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text("{}")
    (artifact / "out" / "meta.json").symlink_to(secret)
    (artifact / "out" / "votes" / "h119-2-0325.json").symlink_to(tmp_path)
    assert cda.check(artifact, committed) == [
        "'out/meta.json': not a regular file",
        "'out/votes/h119-2-0325.json': not a regular file",
    ]


def test_a_name_with_a_line_break_is_printed_escaped(artifact, committed):
    (artifact / "out" / "x\n::error::y.json").write_text("{}")
    [problem] = cda.check(artifact, committed)
    assert "\n" not in problem and problem.startswith("'out/x\\n::error::y.json'")


def test_invalid_json_fails(artifact, committed):
    (artifact / "out" / "votes" / "h119-2-0324.json").write_text("{")
    (artifact / "out" / "meta.json").write_bytes(b'"\xff"')
    problems = cda.check(artifact, committed)
    assert [p.split(":")[0] for p in problems] == ["'out/meta.json'", "'out/votes/h119-2-0324.json'"]
    assert all("not valid JSON" in p for p in problems)


def test_missing_parts_fail(artifact, committed):
    (artifact / "bot" / "state.json").unlink()
    assert cda.check(artifact, committed) == ["bot/state.json: missing"]


def test_size_and_count_caps(artifact, committed, monkeypatch):
    monkeypatch.setattr(cda, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(cda, "MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(cda, "MAX_FILES", 5)
    (artifact / "out" / "votes.json").write_text('{"votes": [' + "1," * 40 + "1]}")
    problems = cda.check(artifact, committed)
    total = sum(p.stat().st_size for p in artifact.rglob("*") if p.is_file())
    big = (artifact / "out" / "votes.json").stat().st_size
    assert f"'out/votes.json': {big} bytes, over the 10 limit" in problems
    assert "'out/votes/h119-2-0324.json': 2 bytes, over the 10 limit" not in problems
    assert problems[-2:] == [f"{total} bytes in all, over the 100 limit", "6 files, over the 5 limit"]


def test_main_exits_1_and_lists_problems(artifact, capsys, monkeypatch, committed):
    monkeypatch.setattr(cda, "COMMITTED_STATE", committed)
    (artifact / "out" / "index.html").write_text("")
    assert cda.main(["check", str(artifact)]) == 1
    assert "data artifact: 'out/index.html': unexpected file" in capsys.readouterr().err
    (artifact / "out" / "index.html").unlink()
    assert cda.main(["check", str(artifact)]) == 0
    assert capsys.readouterr().out == "data artifact: OK\n"
    assert cda.main(["check"]) == 2
