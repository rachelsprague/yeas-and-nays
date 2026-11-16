"""Check the update job's data artifact before the commit job commits it.

The update job runs third-party code (ingest, dbt, the bot's dependencies);
the commit job holds the only write token. This check stands between them, so
a compromised or broken update job can't push arbitrary files to main or move
the bot's state backwards (which would repost old votes). It uses only the
standard library and runs from the commit job's fresh checkout of main:

    python3 -I scripts/check_data_artifact.py <artifact dir>

The artifact holds out/ (data/out) and bot/state.json. Run from the repo
root, so data/bot/state.json is main's committed state. Exits 1 and lists
every problem if anything is wrong. Names from the artifact are printed with
repr(), so a file name can't start a log line with a workflow command.
"""

import json
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMITTED_STATE = ROOT / "data" / "bot" / "state.json"

# What export writes (src/yan/export/json_export.py): a few top-level files, a
# file per vote and a file per member. A new kind of file needs a pattern here.
ALLOWED = [
    re.compile(r"out/[a-z0-9_]+\.json"),
    re.compile(r"out/votes/[hs]\d+-\d+-\d+\.json"),
    re.compile(r"out/members/[A-Z]\d{6}\.json"),
    re.compile(r"bot/state\.json"),
]
ALLOWED_DIRS = {"out", "out/votes", "out/members", "bot"}

# Today: largest file about 2 MB, about 120 MB and 2,200 files in all. The caps
# leave room for growth and stay under GitHub's 50 MB per-file warning.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_FILES = 50_000

CHAMBERS = ("house", "senate")
VOTE_ID = re.compile(r"([hs])(\d+)-(\d+)-(\d+)")


def vote_order(vote_id: str) -> tuple[int, int, int]:
    """(congress, session, roll) for a vote ID like h119-2-0317, as in yan.bot.state."""
    _, congress, session, roll = VOTE_ID.fullmatch(vote_id).groups()
    return int(congress), int(session), int(roll)


def check_files(root: Path) -> tuple[list[str], list[Path]]:
    """Problems with the artifact's layout and sizes, and its files."""
    problems, files, total = [], [], 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            if rel not in ALLOWED_DIRS:
                problems.append(f"{rel!r}: unexpected directory")
        elif not stat.S_ISREG(mode):
            problems.append(f"{rel!r}: not a regular file")
        elif not any(p.fullmatch(rel) for p in ALLOWED):
            problems.append(f"{rel!r}: unexpected file")
        else:
            size = path.lstat().st_size
            if size > MAX_FILE_BYTES:
                problems.append(f"{rel!r}: {size} bytes, over the {MAX_FILE_BYTES} limit")
            total += size
            files.append(path)
    if total > MAX_TOTAL_BYTES:
        problems.append(f"{total} bytes in all, over the {MAX_TOTAL_BYTES} limit")
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files, over the {MAX_FILES} limit")
    for required in ("out", "bot/state.json"):
        if not (root / required).exists():
            problems.append(f"{required}: missing")
    return problems, files


def check_json(root: Path, files: list[Path]) -> list[str]:
    problems = []
    for path in files:
        try:
            json.loads(path.read_bytes())
        except (UnicodeDecodeError, ValueError) as e:
            problems.append(f"{path.relative_to(root).as_posix()!r}: not valid JSON ({e})")
    return problems


def read_state(path: Path) -> tuple[dict[str, str | None] | None, list[str]]:
    """The last vote ID per chamber, or None and the problems if the file isn't
    exactly the shape yan.bot.state.save writes."""
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, [f"{path.name}: can't be read ({e})"]
    if not isinstance(doc, dict) or set(doc) != set(CHAMBERS):
        return None, [f"{path.name}: keys must be exactly {', '.join(CHAMBERS)}"]
    state, problems = {}, []
    for chamber in CHAMBERS:
        entry = doc[chamber]
        if not isinstance(entry, dict) or set(entry) != {"last_vote_id"}:
            problems.append(f"{path.name}: {chamber} must be {{\"last_vote_id\": ...}}")
            continue
        vote_id = entry["last_vote_id"]
        if vote_id is not None and not (
            isinstance(vote_id, str) and VOTE_ID.fullmatch(vote_id) and vote_id[0] == chamber[0]
        ):
            problems.append(f"{path.name}: {chamber} last_vote_id {vote_id!r} isn't a {chamber} vote ID")
            continue
        state[chamber] = vote_id
    return (state if not problems else None), problems


def check_state(new_path: Path, committed_path: Path) -> list[str]:
    """The new state is well formed and no chamber's last vote moves backwards."""
    new, problems = read_state(new_path)
    if new is None:
        return problems
    if not committed_path.exists():
        return []
    old, old_problems = read_state(committed_path)
    if old is None:
        return [f"committed {p}" for p in old_problems]
    for chamber in CHAMBERS:
        before, after = old[chamber], new[chamber]
        if before is None:
            continue
        if after is None or vote_order(after) < vote_order(before):
            problems.append(f"state.json: {chamber} last_vote_id goes back from {before} to {after}")
    return problems


def check(root: Path, committed_state: Path | None = None) -> list[str]:
    committed_state = committed_state or COMMITTED_STATE
    problems, files = check_files(root)
    state = root / "bot" / "state.json"
    # state.json is parsed (and its shape checked) by check_state.
    problems += check_json(root, [f for f in files if f != state])
    if state in files:
        problems += check_state(state, committed_state)
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <artifact dir>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"{root}: not a directory", file=sys.stderr)
        return 1
    problems = check(root)
    for problem in problems:
        print(f"data artifact: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("data artifact: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
