#!/usr/bin/env python3
"""PreToolUse hook (Bash): gate every `git push` on a pre-push review.

- No review recorded for the commit being pushed: deny, and tell Claude to run
  the /pre-push skill (public-repo checklist + fresh-agent code and security
  reviews), which records the review when it finishes.
- Review recorded: ask, so the user approves the push against the report.
- Anything else is denied outright: the push must be the whole command
  (`git push`, `git push origin`, or `git push origin main`, on main), and
  the repo's state must not change what it sends (aliases, push refspecs,
  push URLs, an edited or missing git hook).

This is a guard against pushing by accident, not against a determined
attempt to get around it: it only sees command text, which can always be
disguised (variables, scripts). The real check is the git pre-push hook in
.githooks/, which sees the exact commits being pushed; this hook refuses to
allow a push unless that hook is installed (`make hooks`) and unmodified.

Reads the hook payload on stdin; prints nothing for other commands, so they
go through the normal permission flow. If the hook itself fails on a command
that mentions "push", it denies rather than letting the command through.
Standard library only; runs on Python 3.9+ (macOS's /usr/bin/python3).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

HOOKS_PATH = ".githooks"
# git's global options that take a separate value (`-C dir`, `--git-dir dir`).
GLOBAL_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
# The only push forms the review covers: HEAD, or main, to origin.
ALLOWED_ARGS = [[], ["origin"], ["origin", "main"]]
SEPARATORS = {";", "&", "&&", "|", "||", "(", ")", "{", "}", "!"}


def tokens(command: str) -> list[str]:
    """Shell-like tokens, with separators as their own tokens. Raises ValueError on bad quoting."""
    command = command.replace("\\\n", "").replace("`", " ; ").replace("\n", " ; ")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    # No comment handling: shlex would treat `#` mid-word (a URL's `/#x`) as a
    # comment, and with newlines joined, a comment line would hide every line
    # after it. Comment text is just more tokens, so a trailing comment after
    # a push is denied rather than ignored.
    lexer.commenters = ""
    return list(lexer)


def find_pushes(command: str, depth: int = 0) -> list[dict]:
    """Every `git ... push ...` in the command, as {"prefix", "globals", "args"}.

    Unwraps quoting (`\\git`, `"git" push`) and looks inside quoted strings, so
    `sh -c 'git push'` and `eval "git push"` are found too. `git stash push`
    and other subcommands are not pushes.
    """
    pushes, segment = [], []
    for tok in tokens(strip_redirects(command)) + [";"]:
        if tok not in SEPARATORS:
            segment.append(tok)
            continue
        pushes += _push_in_segment(segment)
        if depth < 3:
            for t in segment:
                if any(c.isspace() for c in t):
                    try:
                        pushes += find_pushes(t, depth + 1)
                    except ValueError:
                        pass  # not valid shell on its own (e.g. a message with "can't"), so not run as a command
        segment = []
    return pushes


def _push_in_segment(seg: list[str]) -> list[dict]:
    for i, tok in enumerate(seg):
        if os.path.basename(tok) != "git":
            continue
        j, globals_ = i + 1, []
        while j < len(seg) and seg[j].startswith("-"):
            globals_.append(seg[j])
            if seg[j] in GLOBAL_OPTS_WITH_VALUE and j + 1 < len(seg):
                globals_.append(seg[j + 1])
                j += 1
            j += 1
        if j < len(seg) and seg[j] == "push":
            return [{"prefix": seg[:i], "globals": globals_, "args": seg[j + 1:]}]
    return []


def strip_redirects(command: str) -> str:
    """The command without redirections (`2>&1`, `> /dev/null`, `push>/dev/null`, `<<<x`)."""
    return re.sub(r"\d*(>>?|<<<|<)(&\d+|\s*[^\s;&|]+)", " ", command).strip()


def git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def repo_problem(repo: str, ref: str) -> str | None:
    """Why the repo's own state means the review can't vouch for this push, or None."""
    top = git(repo, "rev-parse", "--show-toplevel")
    hook = os.path.join(top, HOOKS_PATH, "pre-push") if top else ""
    if git(repo, "config", "core.hooksPath") != HOOKS_PATH or not os.access(hook, os.X_OK):
        return f"the git pre-push hook isn't installed in this clone. Run `make hooks` (sets core.hooksPath to {HOOKS_PATH})."
    if git(repo, "status", "--porcelain", "--", HOOKS_PATH):
        return f"{HOOKS_PATH}/ differs from the committed version, so the git pre-push hook can't be trusted."
    aliases = git(repo, "config", "--get-regexp", r"^alias\.").splitlines()
    if any("push" in line.split(maxsplit=1)[-1] for line in aliases):
        return "a git alias runs a push; aliases can skip both push checks. Remove it first."
    push_config = git(repo, "config", "--get-regexp", r"^(remote\.origin\.(push|pushurl|mirror)|remote\.pushdefault"
                      r"|branch\..*\.pushremote|url\..*\.(push)?insteadof)$")
    if (push_config or git(repo, "config", "push.default") not in ("", "simple", "current")
            or git(repo, "config", "branch.main.remote") not in ("", "origin")
            or git(repo, "config", "branch.main.merge") not in ("", "refs/heads/main")):
        return ("git config changes what `git push` sends or where (push refspecs or URLs, url.*.insteadOf, "
                "push.default other than simple/current, or main not tracking origin/main).")
    if ref == "HEAD" and git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        return "the current branch isn't main. The review covers one commit on main."
    return None


def decide(command: str, repo: str) -> tuple[str, str] | None:
    """(decision, reason) for a command that pushes, or None for one that doesn't."""
    flat = re.sub(r"[\"'\\]", "", command)  # `pu""sh`, `--no-v\erify`, `core.hooks''Path`
    if "$'" in command and "git" in command:
        return "deny", "git commands with $'...' quoting can hide a push; write the command without it."
    try:
        pushes = find_pushes(command)
    except ValueError:
        if "git" in flat and "push" in flat:
            return "deny", "Couldn't parse this command to check for a git push. Run `git push` as its own command."
        return None
    if "push" in flat and ("--no-verify" in flat or "hookspath" in flat.lower()):  # also pushes built in a script
        return "deny", "git push refused: --no-verify or a hooksPath setting would switch off the git pre-push hook."
    if not pushes:
        return None

    allowed = [["git", "push", *args] for args in ALLOWED_ARGS]
    if len(pushes) > 1 or tokens(strip_redirects(command)) not in allowed:
        return "deny", ("git push refused: run the push as its own command, exactly `git push`, `git push origin`, "
                        "or `git push origin main` from the repo root, with nothing before or after it. The review "
                        "covers one commit on main; push anything else by hand.")

    ref = "main" if pushes[0]["args"] == ["origin", "main"] else "HEAD"
    if reason := repo_problem(repo, ref):
        return "deny", f"git push refused: {reason}"

    sha = git(repo, "rev-parse", ref)
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if sha and common and os.path.isfile(os.path.join(common, "pre-push-reviewed", sha)):
        return "ask", (f"git push to a PUBLIC repo. The /pre-push review (public-repo checklist, code review, "
                       f"security review) is recorded for {ref} {sha[:7]}. Approve if its report, shown above, "
                       "is acceptable.")
    return "deny", (f"No pre-push review is recorded for {ref} {sha[:7]}. This repo is public: run the /pre-push "
                    "skill first (public-repo checklist plus fresh-agent code and security reviews). It records "
                    "the review for this exact commit; any later commit needs a new review.")


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        command = (payload.get("tool_input") or {}).get("command") or ""
        repo = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
        result = decide(command, repo)
    except Exception as e:  # fail closed: a crash must not let a push through
        if "push" not in raw:
            return
        result = "deny", f"The push hook failed ({type(e).__name__}: {e}); not allowing a command that may push."
    if result is None:
        return
    decision, reason = result
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                      "permissionDecision": decision,
                                      "permissionDecisionReason": reason}}, sys.stdout)


if __name__ == "__main__":
    main()
