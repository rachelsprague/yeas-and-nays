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

It also gates PR and issue text posted to GitHub, which is just as public.
`gh pr create / edit / comment / review` and `gh issue create / edit /
comment` are allowed only as the whole command, with known flags as separate
words and the text from a file (`--body-file`); `gh api` writes to PRs and
issues only as a comment, a review-comment reply or a comment edit with
`-F body=@file`. The file must be a regular file in the repo or a temp
directory, small enough to show in full. Those ask, showing the title and the
whole text, so the user approves exactly what's posted. Every other form is
denied: inline or attached text, stdin, --fill, templates, editors, other
`gh api` writes and graphql mutations, close/reopen with a comment, gh
aliases, and a post chained with or redirected from anything else.

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
import stat
import subprocess
import sys
import tempfile

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


# Heredoc bodies fed to a shell run as commands; any other body (cat into a file, a python
# script) is checked word by word, since what it writes may be run later in the command.
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "source", "."}
HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2")
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=\S*")
# Fallback for text that can't be parsed as shell: `git` and `push` as words, close together on
# one line (not "github", "/pre-push" or "pre-push"), and `gh` ... `merge` likewise.
LOOSE_PUSH = re.compile(r"\bgit\b[^\n;&|]{0,200}?(?<![-/.\w])push\b")
LOOSE_MERGE = re.compile(r"\bgh\b[^\n;&|]{0,200}?(?<![-/.\w])merge\b")
# A gh command that posts PR or issue text, as it may appear inside a script a heredoc writes.
LOOSE_POST = re.compile(r"\bgh\b[^\n;&|]{0,80}?\b(pr|issue)\s+(create|edit|comment|review|close|reopen)\b"
                        r"|\bgh\s+(api|alias)\b")
# Heredoc targets that run what they're fed (scripts), as opposed to cat or git reading text.
INTERPRETERS = SHELLS | {"python", "python3", "node", "ruby", "perl", "uv"}

# Posting commands, and the only flags each may use, every one as a separate token. Flags that
# take a value map to True. Anything else (attached values, --body, --fill, --template,
# --editor, --web) is denied, so the text posted is always the file shown.
REPO_FLAGS = {"-R": True, "--repo": True}
BODY_FLAGS = {"--body-file": True, "-F": True}
POSTING_FLAGS = {
    ("pr", "create"): {**BODY_FLAGS, "--title": True, "-t": True, "--base": True, "-B": True, "--head": True,
                       "-H": True, "--draft": False, "-d": False, "--label": True, "-l": True,
                       "--reviewer": True, "-r": True, "--assignee": True, "-a": True},
    ("pr", "edit"): {**BODY_FLAGS, "--title": True, "-t": True, "--base": True, "-B": True,
                     "--add-label": True, "--remove-label": True, "--add-reviewer": True,
                     "--remove-reviewer": True, "--add-assignee": True, "--remove-assignee": True},
    ("pr", "comment"): {**BODY_FLAGS, "--edit-last": False},
    ("pr", "review"): {**BODY_FLAGS, "--approve": False, "-a": False, "--comment": False, "-c": False,
                       "--request-changes": False, "-r": False},
    ("issue", "create"): {**BODY_FLAGS, "--title": True, "-t": True, "--label": True, "-l": True,
                          "--assignee": True, "-a": True},
    ("issue", "edit"): {**BODY_FLAGS, "--title": True, "-t": True, "--add-label": True, "--remove-label": True,
                        "--add-assignee": True, "--remove-assignee": True},
    ("issue", "comment"): {**BODY_FLAGS, "--edit-last": False},
}
# close and reopen post text only with a comment.
COMMENTING_ACTIONS = {("pr", "close"), ("pr", "reopen"), ("issue", "close"), ("issue", "reopen")}
# The only `gh api` writes allowed: a comment, a reply to a review comment, or an edit of a comment.
API_COMMENT = re.compile(r"/?repos/[\w.-]+/[\w.-]+/(issues/\d+/comments|pulls/\d+/comments(/\d+/replies)?)")
API_COMMENT_EDIT = re.compile(r"/?repos/[\w.-]+/[\w.-]+/(issues|pulls)/comments/\d+")
API_TEXT_ENDPOINT = re.compile(r"(^|/)repos/[^\s]*/(pulls|issues|comments|reviews)(/|$|\?)|(^|/)graphql$")
API_WRITE_OPTS = ("-f", "-F", "--field", "--raw-field", "--input", "-X", "--method")
MAX_BODY_BYTES = 20_000  # shown in full in the approval prompt; anything longer is refused


def split_heredocs(command: str) -> tuple[str, list[str], list[str]]:
    """(shell text, other bodies, interpreter bodies): the command with heredoc bodies taken
    out, bodies fed to a shell (or piped onward, as in `cat <<EOF | sh`) put back as plain
    command lines, and every other body (a note written with cat, a `python3 -` script)
    returned separately for a word-level check; the third list is the subset fed to an
    interpreter (`python3 -`), as opposed to text read by cat or git. A `<<WORD` whose
    delimiter line never comes (say, inside a quoted commit message) isn't a heredoc, so the
    lines after it stay commands."""
    lines, kept, scripts, run = command.split("\n"), [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in HEREDOC.finditer(line):
            strip_tabs, delimiter = match.group(1) == "-", match.group(3)
            end = i
            while end < len(lines) and (lines[end].lstrip("\t") if strip_tabs else lines[end]) != delimiter:
                end += 1
            if end == len(lines):
                continue  # no delimiter line: not a heredoc
            body, i = lines[i:end], end + 1
            target = heredoc_target(line[:match.start()])
            if target in SHELLS or "|" in line[match.end():]:
                kept += body
            else:
                scripts.append("\n".join(body))
                if target in INTERPRETERS:
                    run.append(scripts[-1])
    return "\n".join(kept), scripts, run


def heredoc_target(before: str) -> str:
    """The command a heredoc feeds: the first word of the last command before `<<`."""
    segment = re.split(r"[;&|()]", before)[-1].split()
    while segment and (ASSIGNMENT.fullmatch(segment[0]) or segment[0] in ("env", "command", "exec")):
        segment = segment[1:]
    return os.path.basename(segment[0].strip("\"'\\")) if segment else ""


def find_pushes(command: str) -> list[dict]:
    """Every `git ... push ...` in the command, as {"prefix", "globals", "args"}.

    Unwraps quoting (`\\git`, `"git" push`) and looks inside quoted strings, so
    `sh -c 'git push'` and `eval "git push"` are found too. `git stash push`
    and other subcommands are not pushes.
    """
    return _scan(command, _push_in_segment)


def finds_pr_merge(command: str) -> bool:
    """Whether the command merges a PR: `gh pr merge`, or a `gh api` call to a PR's merge
    endpoint or the mergePullRequest mutation. Checked per command, like pushes, so
    `gh pr view 1 && git merge origin/main` isn't one."""
    return bool(_scan(command, _pr_merge_in_segment))


def _scan(command: str, in_segment, depth: int = 0) -> list:
    found, segment = [], []
    for tok in tokens(strip_redirects(command)) + [";"]:
        if tok not in SEPARATORS:
            segment.append(tok)
            continue
        found += in_segment(segment)
        if depth < 3:
            for t in segment:
                if any(c.isspace() for c in t):
                    try:
                        found += _scan(t, in_segment, depth + 1)
                    except ValueError:
                        pass  # not valid shell on its own (e.g. a message with "can't"), so not run as a command
        segment = []
    return found


def _pr_merge_in_segment(seg: list[str]) -> list[bool]:
    for i, tok in enumerate(seg):
        if os.path.basename(tok) != "gh":
            continue
        rest = seg[i + 1:]
        # `pr` then `merge`, wherever flags put them (`gh -R o/r pr merge 3`, `gh pr -R o/r merge`).
        if "pr" in rest and "merge" in rest[rest.index("pr") + 1:]:
            return [True]
        if "api" in rest and any(re.search(r"/pulls/\d+/merge\b|mergePullRequest", a) for a in rest):
            return [True]
        if "alias" in rest and any("merge" in a for a in rest):  # `gh alias set m 'pr merge'`
            return [True]
    return []


def find_posts(command: str, depth: int = 0) -> list[dict]:
    """Every gh command that posts PR or issue text (or sets an alias), as {"kind", "args"}.

    Looks at the command's own words, and inside the strings it hands to a shell (`sh -c`,
    `eval`), but not inside other quoted text, so `git commit -m "... gh pr comment ..."`
    isn't a post."""
    found, segment = [], []
    for tok in tokens(strip_redirects(command)) + [";"]:
        if tok not in SEPARATORS:
            segment.append(tok)
            continue
        found += _post_in_segment(segment)
        if depth < 3 and any(os.path.basename(t) in SHELLS | {"eval"} for t in segment):
            for t in segment:
                if any(c.isspace() for c in t):
                    try:
                        found += find_posts(t, depth + 1)
                    except ValueError:
                        pass  # not valid shell on its own, so not run as a command
        segment = []
    return found


def _post_in_segment(seg: list[str]) -> list[dict]:
    for i, tok in enumerate(seg):
        if os.path.basename(tok) == "gh" and (kind := _post_kind(seg[i + 1:])):
            return [{"kind": kind, "args": seg[i + 1:]}]
    return []


def _gh_words(args: list[str]) -> list[str]:
    """gh's subcommand words and positional arguments: args that aren't flags or -R values."""
    words, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in REPO_FLAGS:
            skip = True
        elif not a.startswith("-"):
            words.append(a)
    return words


def _post_kind(args: list[str]) -> str | None:
    words = _gh_words(args)
    pair = tuple(words[:2])
    if pair in (("alias", "set"), ("alias", "import")):
        return "alias"
    if pair in POSTING_FLAGS:
        return "post"
    if pair in COMMENTING_ACTIONS and any(a in ("-c", "--comment") or a.startswith(("-c", "--comment="))
                                          for a in args):
        return "close-comment"
    if words[:1] == ["api"] and _api_writes_text(args):
        return "api"
    return None


def _api_writes_text(args: list[str]) -> bool:
    """Whether `gh api <args>` writes to a PR, issue, comment or review, or runs a graphql
    mutation. gh POSTs when given fields, unless the method says otherwise."""
    if not any(API_TEXT_ENDPOINT.search(a) for a in args if not a.startswith("-")):
        return False
    method = ""
    for k, a in enumerate(args):
        if a in ("-X", "--method") and k + 1 < len(args):
            method = args[k + 1]
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
    fields = [a for a in args if a.startswith(("-f", "-F", "--field", "--raw-field", "--input"))]
    if any(a.strip("/") == "graphql" for a in args):
        # A query given inline can be read; one from a file, --input or a mutation can't be checked.
        values = [args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-f", "-F", "--field", "--raw-field")]
        return (len(values) != len(fields) or any("mutation" in a for a in args)
                or any(v.split("=", 1)[-1].startswith("@") for v in values))
    return method.upper() not in ("", "GET") or (bool(fields) and method.upper() != "GET")


def _allowed_roots(repo: str) -> list[str]:
    """Where a body file may live: the repository, and the temp directories (the scratchpad)."""
    roots = [git(repo, "rev-parse", "--show-toplevel") or repo, tempfile.gettempdir(), "/tmp"]
    return [os.path.realpath(r) for r in roots]


def read_body(path: str, repo: str) -> tuple[str | None, str]:
    """(text, "") for a body file the approval prompt can show in full, else (None, why not).
    A regular file under the repo or a temp directory, at most MAX_BODY_BYTES, UTF-8."""
    if path == "-" or path.startswith("~") or "$" in path:
        return None, f"{path!r} isn't a plain path to a file (no stdin, ~ or variables)."
    full = os.path.realpath(os.path.join(repo, path))
    if not any(full == r or full.startswith(r + os.sep) for r in _allowed_roots(repo)):
        return None, f"{path} is outside the repository and the temp directories."
    try:
        st = os.stat(full)
    except OSError:
        return None, f"can't read {path}."
    if not stat.S_ISREG(st.st_mode):
        return None, f"{path} isn't a regular file."
    if st.st_size > MAX_BODY_BYTES:
        return None, f"{path} is over {MAX_BODY_BYTES} bytes, too long to show in full for approval."
    try:
        with open(full, "rb") as f:
            return f.read(MAX_BODY_BYTES + 1).decode("utf-8"), ""
    except (OSError, UnicodeDecodeError):
        return None, f"{path} isn't readable UTF-8 text."


FILE_ONLY = ("Text posted to GitHub is public: write it to a file, run the public-repo checklist (CLAUDE.md) "
             "over it, and post it from the file as a command of its own: `gh pr comment <N> --body-file "
             "<file>` (or pr/issue create, edit, review with --body-file; gh api: -F body=@<file>), each "
             "flag and its value as separate words.")


def post_decision(post: dict, command: str, repo: str) -> tuple[str, str]:
    """Ask, showing the title and body to be posted, for an allowed shape; deny anything else."""
    kind, args = post["kind"], post["args"]
    if kind == "alias":
        return "deny", "gh aliases can hide a post or merge from this hook; run the gh command itself."
    if kind == "close-comment":
        return "deny", f"Closing or reopening with a comment posts unreviewed text. Post the comment first. {FILE_ONLY}"
    # The whole command, so nothing before it changes the file or the directory, and nothing
    # feeds it stdin.
    if (strip_redirects(command) != command.strip() or tokens(command) != ["gh", *args]
            or any("$" in a for a in args)):
        return "deny", f"Post to GitHub with the gh command alone: no redirects, pipes, cd, $ or && around it. {FILE_ONLY}"

    if kind == "api":
        return _api_post_decision(args, repo)

    pair = tuple(_gh_words(args)[:2])
    allowed = {**REPO_FLAGS, **POSTING_FLAGS[pair]}
    titles, bodies, positional = [], [], []
    k = 0
    while k < len(args):
        a = args[k]
        if not a.startswith("-"):
            positional.append(a)
        elif a not in allowed:
            return "deny", f"gh {' '.join(pair)}: {a} isn't allowed here. {FILE_ONLY}"
        elif allowed[a]:
            if k + 1 >= len(args) or args[k + 1].startswith("-"):
                return "deny", f"gh {' '.join(pair)}: {a} needs a value. {FILE_ONLY}"
            if a in ("--title", "-t"):
                titles.append(args[k + 1])
            elif a in BODY_FLAGS:
                bodies.append(args[k + 1])
            k += 1
        k += 1
    if len(positional) != (2 if pair[1] == "create" else 3):
        return "deny", f"gh {' '.join(pair)}: expected {'no' if pair[1] == 'create' else 'one'} PR or issue argument."
    if len(bodies) > 1 or len(titles) > 1:
        return "deny", f"gh {' '.join(pair)}: give one title and one body file at most."
    if not bodies and pair[1] in ("create", "comment"):
        return "deny", f"gh {' '.join(pair)} needs --body-file. {FILE_ONLY}"
    shown = [f"Title: {titles[0]}"] if titles else []
    for path in bodies:
        text, why = read_body(path, repo)
        if text is None:
            return "deny", f"gh {' '.join(pair)}: {why} {FILE_ONLY}"
        shown.append(f"--- {path} (posted in full) ---\n{text}")
    return "ask", (f"gh {' '.join(pair)} posts to a PUBLIC repo:\n{' '.join(args)}\n\n"
                   + ("\n\n".join(shown) or "(no title or body text)")
                   + "\n\nApprove only if this text passed the public-repo checklist.")


def _api_post_decision(args: list[str], repo: str) -> tuple[str, str]:
    """Allow only a comment, a review-comment reply or a comment edit, from a file via -F body=@file."""
    endpoint, method, body = None, "", None
    k = 1  # args[0] is "api"
    while k < len(args):
        a = args[k]
        if a in ("-X", "--method") and k + 1 < len(args):
            method, k = args[k + 1].upper(), k + 2
        elif a == "-F" and k + 1 < len(args) and args[k + 1].startswith("body=@") and body is None:
            body, k = args[k + 1][len("body=@"):], k + 2
        elif not a.startswith("-") and endpoint is None:
            endpoint, k = a, k + 1
        else:
            return "deny", f"gh api: {a} isn't allowed in a write to a PR or issue. {FILE_ONLY}"
    shape_ok = ((endpoint and API_COMMENT.fullmatch(endpoint) and method in ("", "POST"))
                or (endpoint and API_COMMENT_EDIT.fullmatch(endpoint) and method == "PATCH"))
    if not shape_ok or body is None:
        return "deny", ("gh api writes to PRs and issues are limited to posting, replying to or editing a "
                        f"comment with -F body=@<file>. {FILE_ONLY}")
    text, why = read_body(body, repo)
    if text is None:
        return "deny", f"gh api: {why} {FILE_ONLY}"
    return "ask", (f"gh api writes to a PUBLIC repo:\n{' '.join(args)}\n\n--- {body} (posted in full) ---\n{text}"
                   "\n\nApprove only if this text passed the public-repo checklist.")



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
    """The checked-out branch, or "" when HEAD is detached. (Not `symbolic-ref --short`,
    which gives `heads/<name>` when a tag has the same name.)"""
    return git(repo, "branch", "--show-current")


def decide(command: str, repo: str) -> tuple[str, str] | None:
    """(decision, reason) for a command that pushes, or None for one that doesn't."""
    if "$'" in command and ("git" in command or "gh" in command):  # before heredocs are split out
        return "deny", "git and gh commands with $'...' quoting can hide a push or merge; write the command without it."
    command, scripts, run_scripts = split_heredocs(command)
    # `pu""sh`, `--no-v\erify`, `core.hooks''Path`
    flat = re.sub(r"[\"'\\]", "", "\n".join([command, *scripts]))
    unquote = lambda s: re.sub(r"[\"'\\]", "", s)  # noqa: E731
    if any(LOOSE_PUSH.search(unquote(s)) or LOOSE_MERGE.search(unquote(s)) for s in scripts):
        return "deny", ("A heredoc in this command mentions git push or gh pr merge, and what it writes may be run. "
                        "Run the push as its own command (or merge on GitHub); for notes, write the text to a file.")
    # Posts only in scripts that run (python3 - <<EOF), so a commit message or note that
    # mentions `gh pr create` isn't refused.
    if any(LOOSE_POST.search(unquote(s)) for s in run_scripts):
        return "deny", ("A script in this command runs a gh command that posts to GitHub. Post with the gh command "
                        f"itself. {FILE_ONLY}")
    try:
        pushes = find_pushes(command)
        if finds_pr_merge(command):
            return "deny", "PRs are merged by the maintainer on GitHub (squash merge). Open the PR and stop there."
        posts = find_posts(command)
    except ValueError:
        if LOOSE_PUSH.search(flat) or LOOSE_MERGE.search(flat) or LOOSE_POST.search(unquote(command)):
            return "deny", ("Couldn't parse this command to check for a git push, PR merge or text posted to "
                            "GitHub. Run it on its own.")
        return None
    if "push" in flat and ("--no-verify" in flat or "hookspath" in flat.lower()):  # also pushes built in a script
        return "deny", "git push refused: --no-verify or a hooksPath setting would switch off the git pre-push hook."
    if posts:
        if pushes or len(posts) > 1:
            return "deny", "Post to GitHub as a command of its own (one gh command, nothing before or after it)."
        return post_decision(posts[0], command, repo)
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
    except Exception as e:  # fail closed: a crash must not let a push, merge or post through
        if "push" not in raw and "merge" not in raw and not re.search(r"\bgh\b", raw):
            return
        result = "deny", (f"The push hook failed ({type(e).__name__}: {e}); not allowing a command that may push "
                          "or post to GitHub.")
    if result is None:
        return
    decision, reason = result
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                      "permissionDecision": decision,
                                      "permissionDecisionReason": reason}}, sys.stdout)


if __name__ == "__main__":
    main()
