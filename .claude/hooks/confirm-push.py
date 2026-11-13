#!/usr/bin/env python3
"""PreToolUse hook (Bash): gate every `git push` on a pre-push review.

Work lands through pull requests: a session pushes its own branch and opens a
PR, and the maintainer squash-merges it on GitHub. So:

- No review recorded for the commit being pushed: deny, and tell Claude to run
  the /pre-push skill (public-repo checklist + fresh-agent code and security
  reviews), which records the review when it finishes.
- Review recorded: ask, so the user approves the push against the report.
- Anything else is denied outright: the push must be the whole command
  (`git push`, `git push origin`, or `git push [-u] origin <branch>`, where
  <branch> is the current branch and isn't main), and the repo's state must
  not change what it sends (aliases, push refspecs, push URLs, an edited or
  missing git hook). Pushing main and `gh pr merge` are denied: PRs are merged
  on GitHub by the maintainer.

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
# Branch names the hook will push: plain names, nothing git or the shell could read as more.
BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
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


def hooks_dir(repo: str) -> str | None:
    """The directory git runs hooks from, if core.hooksPath is one of the forms we accept.

    `make hooks` writes `.githooks`, which git resolves against the worktree being
    pushed from; Claude Code's worktree tool rewrites it in the shared config to an
    absolute path, the main checkout's `.githooks`. Accept exactly those strings:
    resolving other spellings here (`..`, `~`) wouldn't match how git does it.
    """
    top = git(repo, "rev-parse", "--show-toplevel")
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not top or not common:
        return None
    configured = git(repo, "config", "core.hooksPath")
    if configured == HOOKS_PATH:
        return os.path.join(top, HOOKS_PATH)
    # The main checkout is the parent of the common .git directory (in it, that's `top` too).
    checkouts = {top, os.path.dirname(common)} if os.path.basename(common) == ".git" else {top}
    for checkout in checkouts:
        if configured == os.path.join(checkout, HOOKS_PATH):
            return configured
    return None


def repo_problem(repo: str, branch: str, explicit: bool) -> str | None:
    """Why the repo's own state means the review can't vouch for pushing `branch`, or None.

    `explicit` is a push that names `origin <branch>`: it goes to origin's branch of the
    same name whatever the branch tracks (a new worktree branch often tracks origin/main),
    so only a bare `git push` needs the branch to track origin/<branch>.
    """
    hooks = hooks_dir(repo)
    if not hooks or not os.access(os.path.join(hooks, "pre-push"), os.X_OK):
        return f"the git pre-push hook isn't installed in this clone. Run `make hooks` (sets core.hooksPath to {HOOKS_PATH})."
    if git(os.path.dirname(hooks), "status", "--porcelain", "--", HOOKS_PATH):
        return f"{HOOKS_PATH}/ differs from the committed version, so the git pre-push hook can't be trusted."
    aliases = git(repo, "config", "--get-regexp", r"^alias\.").splitlines()
    if any("push" in line.split(maxsplit=1)[-1] for line in aliases):
        return "a git alias runs a push; aliases can skip both push checks. Remove it first."
    push_config = git(repo, "config", "--get-regexp", r"^(remote\.origin\.(push|pushurl|mirror)|remote\.pushdefault"
                      r"|branch\..*\.pushremote|url\..*\.(push)?insteadof)$")
    tracking_ok = explicit or (git(repo, "config", f"branch.{branch}.remote") in ("", "origin")
                               and git(repo, "config", f"branch.{branch}.merge") in ("", f"refs/heads/{branch}"))
    if push_config or git(repo, "config", "push.default") not in ("", "simple", "current") or not tracking_ok:
        return ("git config changes what `git push` sends or where (push refspecs or URLs, url.*.insteadOf, "
                f"push.default other than simple/current, or {branch} not tracking origin/{branch}).")
    return None


def current_branch(repo: str) -> str:
    """The checked-out branch, or "" when HEAD is detached."""
    return git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")


def decide(command: str, repo: str) -> tuple[str, str] | None:
    """(decision, reason) for a command that pushes, or None for one that doesn't."""
    flat = re.sub(r"[\"'\\]", "", command)  # `pu""sh`, `--no-v\erify`, `core.hooks''Path`
    if re.search(r"\bgh\b.*\bpr\b.*\bmerge\b", flat):
        return "deny", "PRs are merged by the maintainer on GitHub (squash merge). Open the PR and stop there."
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

    branch = current_branch(repo)
    if branch == "main":
        return "deny", ("git push refused: changes land through pull requests. Work on a branch (in a worktree), "
                        "run /pre-push, push the branch, and open a PR; the maintainer merges it.")
    if not branch or not BRANCH_NAME.fullmatch(branch):
        return "deny", "git push refused: check out a branch with a plain name (letters, digits, . _ / -) first."

    allowed = [["git", "push"], ["git", "push", "origin"], ["git", "push", "origin", branch],
               ["git", "push", "-u", "origin", branch], ["git", "push", "--set-upstream", "origin", branch]]
    if len(pushes) > 1 or tokens(strip_redirects(command)) not in allowed:
        return "deny", (f"git push refused: run the push as its own command, exactly `git push -u origin {branch}` "
                        "(or `git push` once it tracks origin), with nothing before or after it. The review covers "
                        "the current branch's commit; push anything else by hand.")

    if reason := repo_problem(repo, branch, explicit=branch in pushes[0]["args"]):
        return "deny", f"git push refused: {reason}"

    sha = git(repo, "rev-parse", "HEAD")
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if sha and common and os.path.isfile(os.path.join(common, "pre-push-reviewed", sha)):
        return "ask", (f"git push of {branch} to a PUBLIC repo. The /pre-push review (public-repo checklist, code "
                       f"review, security review) is recorded for {sha[:7]}. Approve if its report, shown above, "
                       "is acceptable.")
    return "deny", (f"No pre-push review is recorded for {branch} {sha[:7]}. This repo is public: run the /pre-push "
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
