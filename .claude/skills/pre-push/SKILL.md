---
name: pre-push
description: Review every outgoing commit before a git push in this public repo — the public-repo checklist, plus a code review and a security review by fresh agents that didn't write the code — then record the review so the push hook allows the push. Use before any `git push`, or when the user says "/pre-push", "review before pushing", or "push".
---

# Pre-push review

This repo is public, and `.claude/hooks/confirm-push.sh` blocks `git push`
until this review has been recorded for the exact commit being pushed. The
point is independence: the agent that wrote the code is the worst-placed to
review it, so the code and security reviews run in fresh agents that see
only the diff and the repo.

## 1. Scope

```
git fetch origin
git log --format='%h %an <%ae> %s' origin/main..HEAD
git status --short
```

- If `origin/main` has commits that `HEAD` doesn't, stop and rebase first;
  the review has to cover what will actually be pushed.
- If the working tree has changes under `data/out/` from a local export,
  restore them (`git checkout -- data/out`): CI regenerates that data.
  Anything else uncommitted: ask, don't discard.
- Nothing outgoing: say so and stop.

## 2. Three reviews, in parallel

Launch the two agents in one message, then do the checklist yourself while
they run. The agents only read and search, so they don't need a worktree.

**a. Public-repo checklist (you).** Follow "Public repo: review before every
push" in `CLAUDE.md`: read `git log -p origin/main..HEAD` commit by commit,
including messages and author emails. Secrets, personal info, commit
identity (GitHub noreply only), neutrality, internal notes, data size,
third-party content.

**b. Code review (fresh `general-purpose` agent).** Prompt it with the
commit range and this brief:

> You are reviewing commits `origin/main..HEAD` in this repo before they're
> pushed to a public repository. You did not write them. Read `CLAUDE.md`,
> `STYLE.md` and `README.md` first, then every commit's diff
> (`git log -p origin/main..HEAD`) and whatever surrounding code you need.
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

**c. Security review (fresh `general-purpose` agent).** Prompt:

> You are doing a security review of commits `origin/main..HEAD` in this
> public repo before they're pushed. You did not write them. Read
> `CLAUDE.md`, then every commit's diff and the code it touches. Check:
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

## 4. Record the review

Only when there are no unresolved high-severity findings (fixed, or the
user explicitly accepts them), record the review for the current HEAD:

```
d="$(git rev-parse --git-dir)/pre-push-reviewed"; mkdir -p "$d" && touch "$d/$(git rev-parse HEAD)"
```

The marker lives inside `.git/`, so it's never committed. Any new commit
changes HEAD, so the hook will require a fresh review.

## 5. Push

Run `git push`. The hook still asks the user to approve; the report above
is what they approve against. If anything is committed after the review,
start again from step 1.
