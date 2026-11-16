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
    for name in ("votes", "members", "meta", "floor_schedule"):
        (root / "out" / f"{name}.json").write_text("{}")
    for vote_id in ("h119-2-0324", "s119-2-0262", "h120-1-0001", "s120-1-0001"):
        (root / "out" / "votes" / f"{vote_id}.json").write_text("{}")
    (root / "out" / "members" / "A000055.json").write_text("{}")
    (root / "bot" / "state.json").write_text(json.dumps(state("h119-2-0324", "s119-2-0262")))
    return root


def test_an_artifact_like_exports_passes(artifact, committed):
    assert cda.check(artifact, committed) == []


def test_state_with_no_change_or_from_null_passes(artifact, committed, tmp_path):
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h119-2-0323", "s119-2-0262")))
    assert cda.check(artifact, committed) == []
    # From null, or with no committed state yet (a fresh repo), to exported votes.
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h119-2-0324", "s119-2-0262")))
    assert cda.check(artifact, tmp_path / "missing.json") == []
    committed.write_text(json.dumps(state(None, None)))
    assert cda.check(artifact, committed) == []


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
    "out/Extra.json",
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
    (artifact / "out" / "meta.json").unlink()
    (artifact / "out" / "meta.json").symlink_to(secret)
    (artifact / "out" / "votes" / "h119-2-0325.json").symlink_to(tmp_path)
    assert cda.check(artifact, committed) == [
        "'out/meta.json': not a regular file",
        "'out/votes/h119-2-0325.json': not a regular file",
    ]


@pytest.mark.parametrize("mode", [0o755, 0o744, 0o654, 0o645])
def test_executable_files_fail(artifact, committed, mode):
    (artifact / "out" / "meta.json").chmod(mode)
    (artifact / "bot" / "state.json").chmod(mode)
    assert cda.check(artifact, committed) == [
        "'bot/state.json': executable",
        "'out/meta.json': executable",
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


@pytest.mark.parametrize("rel", cda.REQUIRED)
def test_missing_required_files_fail(artifact, committed, rel):
    # An artifact without them would empty data/out when the commit job replaces it.
    (artifact / rel).unlink()
    assert cda.check(artifact, committed) == [f"{rel}: missing"]


def test_nan_infinity_and_deep_nesting_fail(artifact, committed):
    (artifact / "out" / "meta.json").write_text('{"x": NaN}')
    (artifact / "out" / "members.json").write_text("[-Infinity]")
    (artifact / "out" / "votes.json").write_text("[" * 100_000 + "]" * 100_000)
    assert cda.check(artifact, committed) == [
        "'out/members.json': not valid JSON (-Infinity isn't JSON)",
        "'out/meta.json': not valid JSON (NaN isn't JSON)",
        "'out/votes.json': not valid JSON (nested too deeply)",
    ]


def test_non_ascii_digits_fail(artifact, committed):
    # ١١٩ is "119" in Arabic-Indic digits, which \d would match.
    rel = "out/votes/h١١٩-2-0324.json"
    (artifact / rel).write_text("{}")
    assert cda.check(artifact, committed) == [f"{rel!r}: unexpected file"]
    (artifact / rel).unlink()
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h١١٩-2-0324", "s119-2-0262")))
    [problem] = cda.check(artifact, committed)
    assert problem.endswith("isn't a house vote ID")


def test_state_must_move_to_an_exported_vote(artifact, committed):
    # A jump to a vote far ahead would stop the bot from posting until fixed by hand.
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h9999-9-99999", "s119-2-0262")))
    assert cda.check(artifact, committed) == [
        "state.json: house last_vote_id h9999-9-99999 has no out/votes/h9999-9-99999.json"
    ]
    # Unchanged state needs no file: older votes can leave the export.
    (artifact / "out" / "votes" / "s119-2-0262.json").unlink()
    (artifact / "bot" / "state.json").write_text(json.dumps(state("h119-2-0324", "s119-2-0262")))
    assert cda.check(artifact, committed) == []
    # From null (a fresh repo) too.
    committed.write_text(json.dumps(state(None, None)))
    assert cda.check(artifact, committed) == [
        "state.json: senate last_vote_id s119-2-0262 has no out/votes/s119-2-0262.json"
    ]


def test_size_and_count_caps(artifact, committed, monkeypatch):
    monkeypatch.setattr(cda, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(cda, "MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(cda, "MAX_FILES", 5)
    # Invalid JSON, but over the size cap, so it isn't parsed.
    (artifact / "out" / "votes.json").write_text('{"votes": [' + "1," * 40)
    problems = cda.check(artifact, committed)
    files = [p for p in artifact.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    big = (artifact / "out" / "votes.json").stat().st_size
    assert f"'out/votes.json': {big} bytes, over the 10 limit" in problems
    assert not any("not valid JSON" in p for p in problems)
    assert problems[-2:] == [f"{total} bytes in all, over the 100 limit", f"{len(files)} files, over the 5 limit"]


def test_main_exits_1_and_lists_problems(artifact, capsys, monkeypatch, committed):
    monkeypatch.setattr(cda, "COMMITTED_STATE", committed)
    (artifact / "out" / "index.html").write_text("")
    assert cda.main(["check", str(artifact)]) == 1
    assert "data artifact: 'out/index.html': unexpected file" in capsys.readouterr().err
    (artifact / "out" / "index.html").unlink()
    assert cda.main(["check", str(artifact)]) == 0
    assert capsys.readouterr().out == "data artifact: OK\n"
    assert cda.main(["check"]) == 2
