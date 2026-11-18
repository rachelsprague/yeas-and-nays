---
visibility: public
# true: the hourly pipeline commits to main, so agents never start it.
deny_workflow_run: true
---

# Pre-push settings for yeas-and-nays

Read by the maintainer's shared /pre-push skill. The hook reads only the
frontmatter above.

## Uncommitted changes

Changes under `data/out/` from a local export are safe to restore
(`git checkout -- data/out`): CI regenerates that data. Anything else: ask.

## Public-repo checklist additions

- **Neutrality:** code comments, commit messages, test data, docs and the PR
  text are free of opinions about legislators, parties or policies, to the
  same standard as `STYLE.md`.
- The only maintainer details that may appear are "Rachel Sprague" and
  rachelsprague.com.

## Code review focus

- Edge cases: Speaker elections, Senate tie-breaks, members with no
  portrait, votes with no bill, broken links or routes, Liquid that fails
  silently.
- New dbt models have unique/not-null/relationship tests.
- Export output stays deterministic.
- The bot still defaults to dry run.
- User-facing copy follows `STYLE.md`: facts only, parties D, I, R, no
  party or position colors, results tied to their question.

## Security review focus

- The Congress.gov key goes only in the `X-Api-Key` header, never in a URL
  or a log.
- Untrusted text reaching HTML: CRS summary HTML goes through
  `src/yan/export/summary_html.py`; Liquid output of data fields is escaped
  where it lands in attributes or scripts.
- XML parsing uses defusedxml.
- New or changed dependencies in `uv.lock` and `site/Gemfile.lock`, and
  where they come from.

## Backlog and board

Findings that aren't fixed before the push go in `BOARD.md` as one-line
items (Later, or Next if they matter soon), with any detail in
`backlog/<slug>.md`. Once the PR is open, leave the worktree (keep it) and
in the main checkout's `BOARD.md` add ` — PR #N, awaiting merge` to the
item's line in Now, and to each bundled item still in the PR, keeping the
claims (`CLAUDE.md` > Claiming items).

## After merge

From the main checkout: `git pull --ff-only` on main, `git worktree remove`
the worktree, `git branch -D` the branch, then move the board item (and each
bundled item, on its own line) to Done with the PR number.
