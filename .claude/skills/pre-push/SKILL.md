---
name: pre-push
description: Review a branch's commits before pushing it and opening a PR in this public repo — the public-repo checklist (including the PR text), plus a code review and a security review by fresh agents that didn't write the code — then record the review, push the branch, and open the PR. Also covers text posted to a PR later (comments, review replies, description edits). Use before any `git push` or any PR/issue comment or description edit, or when the user says "/pre-push", "review before pushing", "push", "open a PR", or "comment on the PR".
---

# Pre-push review

This repo is public, and work lands through pull requests: a session pushes
its own branch, opens a PR, and the maintainer squash-merges it on GitHub.
Two hooks block a push until this review has been recorded for the exact
commit being pushed: `.claude/hooks/confirm-push.py` (Claude Code, checks
the command; it also denies pushing main and `gh pr merge`) and
`.githooks/pre-push` (git, checks the commits actually pushed; install once
per clone with `make hooks`). A pushed branch is public as soon as it's
pushed, so the review comes first. The point is independence: the agent
that wrote the code is the worst-placed to review it, so the code and
security reviews run in fresh agents that see only the diff and the repo.

## 1. Scope

Run this from the branch's worktree, not from main.

```
git fetch origin
git branch --show-current
git log --format='%h %an <%ae> %s' origin/main..HEAD
git status --short
```

- On main, or nothing outgoing: say so and stop. Work belongs on a branch.
- If `origin/main` has commits the branch doesn't, bring them in first so
  the review covers what the PR will merge: `git rebase origin/main` if the
  branch has never been pushed; `git merge origin/main` if it has (no force
  pushes; the squash merge flattens it anyway).
- If the branch is already on origin (a PR being updated), the new commits
  are `git log --cc -p origin/<branch>..HEAD --not origin/main` (this leaves
  out the main commits a merge brought in, and keeps the merge itself);
  focus the reviews there, and check the rest only for how they interact.
- If the working tree has changes under `data/out/` from a local export,
  restore them (`git checkout -- data/out`): CI regenerates that data.
  Anything else uncommitted: ask, don't discard.

Draft the PR title and body now (what changed and why, how it was tested;
no session links), the body in a file in your scratchpad: they're public
too, so the checklist covers them. Never put the body on the command line:
Markdown backticks inside shell quotes run as commands.

Always read diffs with `git log -p --cc`: plain `-p` shows nothing for a
merge commit, so a conflict resolution would go out unreviewed. `--cc`
still hides a conflict resolved by taking one side outright, so also read
the net `git diff origin/main...HEAD` when the branch has a merge.

## 2. Three reviews, in parallel

Launch the two agents in one message, then do the checklist yourself while
they run. The agents only read and search, so they don't need a worktree.
Run both on Sonnet (`model: "sonnet"`): they read a lot and write little,
and you check their findings in step 3 anyway.

**a. Public-repo checklist (you).** Follow "Public repo: review before every
push" in `CLAUDE.md`: read `git log -p --cc origin/main..HEAD` commit by commit,
including messages and author emails, and the drafted PR title and body.
Secrets, personal info, commit identity (GitHub noreply only), neutrality,
internal notes, data size, third-party content.

**b. Code review (fresh `general-purpose` agent, Sonnet).** Prompt it with the
commit range and this brief:

> You are reviewing commits `origin/main..HEAD` in this repo before they're
> pushed to a public repository. You did not write them. Read `CLAUDE.md`,
> `STYLE.md` and `README.md` first, then every commit's diff
> (`git log -p --cc origin/main..HEAD`) and whatever surrounding code you need.
> Report correctness bugs first: wrong logic, unhandled edge cases (Speaker
> elections, Senate tie-breaks, members with no portrait, votes with no
> bill), broken links or routes, Liquid that fails silently. Then project
> rules: new dbt models have unique/not-null/relationship tests, export
> output stays deterministic, the bot still defaults to dry run, user-facing
> copy follows `STYLE.md` (facts only, parties D, I, R, no party or position
> colors, results tied to their question). Then tests that are missing for
> new behavior. For each finding: file:line, what's wrong, a concrete
> failing case, and severity (high = wrong data or broken page shipped;
> medium = likely bug; low = cleanup). Verify each finding against the code
> before reporting it; drop anything you can't support. Don't edit files.

**c. Security review (fresh `general-purpose` agent, Sonnet).** Prompt:

> You are doing a security review of commits `origin/main..HEAD` in this
> public repo before they're pushed. You did not write them. Read
> `CLAUDE.md`, then every commit's diff (`git log -p --cc origin/main..HEAD`)
> and the code it touches. Check:
> secrets or credentials anywhere in the diff or history range (including
> test fixtures and logs); GitHub Actions — secrets passed only to the steps
> that need them, third-party actions pinned by commit SHA, least-privilege
> `permissions`, no untrusted input (`github.event.*`) interpolated into
> `run:`; the Congress.gov key sent only as the `X-Api-Key` header and never
> logged or put in a URL; untrusted text reaching HTML (CRS summary HTML
> goes through `src/yan/export/summary_html.py`; Liquid output of data
> fields must be escaped where it lands in attributes or scripts); XML
> parsing uses defusedxml; new or changed dependencies in `uv.lock` /
> `site/Gemfile.lock` and where they come from. For each finding: file:line,
> the risk, how it could be exploited or leak, severity, and the fix. Verify
> before reporting. Don't edit files.

## 3. Report

One combined report to the user, short, highest severity first:

- **Public-repo checklist:** "nothing flagged", or the findings.
- **Code review:** findings, or "no findings".
- **Security:** findings, or "no findings".

Read the agents' findings critically before relaying them: check any you
doubt against the code, and say which you confirmed. Fix nothing without
the user's go-ahead.

Nothing gets lost: every finding, at any severity, is either fixed before
the push, dropped because checking showed it was wrong, or added to
`BOARD.md` as a one-line item (Later, or Next if it matters soon). Do this
without being asked, and end the report by saying which findings went
where.

## 4. Record the review

Only when there are no unresolved high-severity findings (fixed, or the
user explicitly accepts them), record the review for the current HEAD, as a
command of its own (the Claude Code hook checks before a command runs, so a
push chained after this in the same command is denied):

```
d="$(git rev-parse --path-format=absolute --git-common-dir)/pre-push-reviewed"; mkdir -p "$d" && touch "$d/$(git rev-parse HEAD)"
```

The marker lives inside `.git/` (shared by all worktrees), so it's never
committed. Every commit in the range was reviewed, but only HEAD needs a
marker: git's pre-push hook checks the tip of each ref being pushed.
The marker is an empty file that anything can create, so the gate guards
against pushing by accident, not against skipping the review on purpose.
Only record it after the review above has actually run. Any new commit
changes HEAD, so the hook will require a fresh review.

## 5. Push the branch

Run `git push -u origin <branch>` (the current branch; `git push` once it
tracks origin/<branch>) as the whole command, with nothing chained before or
after it. Anything else (main, another branch, refspecs, `--force`, `--all`,
`--tags`, `-C`, `cd ... &&`, `--no-verify`) is denied, and so is a push
while a git alias, push refspec or push URL changes what gets sent, or while
`.githooks/` has uncommitted changes. The git hook also refuses
non-fast-forward pushes. The hook still asks the user to approve; the report
above is what they approve against. If anything is committed after the
review, start again from step 1.

## 6. Open the PR, then stop

For a new branch, open the PR with the reviewed title and body, the body
from its file and the title in single quotes (word the title without an
apostrophe):

```
gh pr create --base main --head <branch> --title '<title>' --body-file <body file>
```

For an update to an existing PR, the push is enough. If its body no longer
describes the change, edit it the same way (`gh pr edit <N> --body-file
<file>`) after running the checklist over the new text. Give the user the
PR link.

Then mark the board: leave the worktree (keep it), and in the main
checkout's `BOARD.md` add ` — PR #N, awaiting merge` to the item's line in
Now, keeping the claim (CLAUDE.md > Claiming items).

Don't merge it: the maintainer squash-merges on GitHub (the hook denies
`gh pr merge`). After it's merged (`gh pr view N --json state`), from the
main checkout: `git pull --ff-only` on main, `git worktree remove` the
worktree, `git branch -D` the branch (`-d` refuses, since a squash merge
leaves the branch's own commits off main), and move the board item to Done
with the PR number.

## Posting to a PR later: comments, replies, description edits

Anything posted to GitHub is as public as the code, so a PR comment, a
review comment or reply, an issue comment, or an edit to a PR's title or
description gets the public-repo checklist (step 2a) before it's posted.
It's text, not code, so skip the agent reviews:

1. Write the text to a file in your scratchpad.
2. Run the checklist over it (secrets, personal info, neutrality per
   STYLE.md, internal notes, no session links), and show the user the text.
3. Post it from the file, with the gh command alone (no `cd`, `&&`, pipes
   or redirects around it, each flag and its value as separate words):
   `gh pr comment <N> --body-file <file>`, `gh pr edit <N> --body-file
   <file>`, `gh pr review <N> --comment --body-file <file>`, or for a reply
   to a review comment `gh api repos/<owner>/<repo>/pulls/<N>/comments/<id>/replies
   -F body=@<file>`. To close with a comment, post the comment first, then
   close.

The push hook asks before any of these and shows the title and the whole
file for the user to approve (files over 20,000 bytes are refused rather than
cut). It denies every other way of posting: inline or attached text
(`--body`, `-bfoo`, `-f body=...`), stdin, `--fill`, templates, editors,
every other `gh api` write and graphql mutations, `close`/`reopen -c`, flags
before the action (`gh pr -b x comment`), `gh pr revert`, gh aliases, and any of `` ` `` `$ \ * ? [ ] { } ~ !` or a line break in the
command (the shell would expand them after the check; gh's `{owner}` and
`{repo}` placeholders are fine), so word titles without them. Titles and
body files can't contain control or invisible characters (emoji like ✔️ and
👨‍💻 are fine; keycaps like 1️⃣ aren't), and body files must be UTF-8 text
outside dot directories. The hook reads command text, so gh run from a
script or another program isn't gated: post with the gh command itself.
