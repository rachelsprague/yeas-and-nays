# Yeas & Nays

Nonpartisan data project that tracks recorded (roll call) votes in the U.S. House and Senate.
- Bluesky bot: @yeasandnaysdata.com — posts notable votes as they happen
- Website: yeasandnaysdata.com — every vote, member profiles, stats
- Built by Rachel Sprague. Public repo; doubles as an analytics engineering portfolio piece, so favor clean, tested, well-documented work.

**Read STYLE.md before writing any post template, page copy, or user-facing text.** Facts only, neutral wording, official sources.

## Stack

- **Ingest (Python):** House Clerk roll call XML, Senate roll call XML, Congress.gov API (bills, sponsors), `unitedstates/congress-legislators` (members, party, state, district, social handles).
- **Model:** DuckDB + dbt (dbt-duckdb). Core models: `members`, `votes`, `positions` (one row per member per vote), `bills`. Add dbt tests (unique/not-null keys, accepted values for positions and party).
- **Output:** JSON/Parquet consumed by the site and bot.
- **Bot:** Python + atproto SDK. Filters votes per STYLE.md post rules, posts via app password.
- **Site:** Jekyll on GitHub Pages, pages generated from data files.
- **Schedule:** GitHub Actions, started hourly by cron-job.org via workflow_dispatch: ingest → model → post → build/deploy.

## Secrets (GitHub Actions)

`BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `CONGRESS_API_KEY` (in the `pipeline` environment, limited to `main`), `CLAUDE_CODE_OAUTH_TOKEN` (repository secret; PR review only; a Claude subscription token from `claude setup-token`). Never commit credentials or `.env` files. Send the Congress.gov key as an `X-Api-Key` header, not in URLs.

## Conventions

- Bot must support a dry-run mode that prints posts without publishing; default to dry run locally.
- Persist bot state (last posted vote ID per chamber) in the repo so runs are idempotent.
- Brand assets live in `brand/` (svg, social, favicon). Palette: aubergine #5A3463, paper #F2EFE6, ink #1C1C1C, dark-mode accent #A887B5. Type: Newsreader (display), IBM Plex Sans (UI/body).
- When Rachel asks how something in Congress works (a procedure, a rule, how a kind of vote is decided), answer it, then offer to turn the answer into a page on the site so other readers learn it too. Pages explain how procedures work, not why a particular vote turned out as it did. A definition of a kind of vote (the question voted on) goes in `site/_data/procedures.yml`, with a `match` pattern for that question; anything else becomes its own page. Either way, follow STYLE.md: neutral wording, cite official sources.

## Backlog

Tracked locally, not in GitHub Issues: `BOARD.md` (one line per item, 150 characters or fewer as filed, before any claim or PR note) and `backlog/<slug>.md` for details. Both are gitignored because this repo is public. Don't create GitHub issues for this project.

Start every open item with its priority, `P0` (highest) to `P5`, as in `- P3 Dictionary page: ...`; the board dashboard shows it as a badge. The prefix doesn't count toward the 150 characters. Drop it when an item moves to Done.

Being gitignored, they exist only in the main checkout, and a session isolated in a worktree can't edit them. So board edits bracket worktree work: claim from the main checkout before entering the worktree, and update the board after leaving it.

`/pick` (a global skill) works from this board. When it maps work in flight, ignore `data/out/`: the hourly pipeline regenerates it, so changes there never mean another session is in that area.

### Claiming items

Several sessions may work in this repo at once. Claim an item before starting it so no other session picks it up:

- **Alias:** at your first claim, pick one short lowercase word as your alias, not one already used in a claim on the board, tell the user, and use it for the rest of the session.
- **Claim:** re-read `BOARD.md` right before editing it, then move the item to Now and append ` — claimed by **<alias>** (YYYY-MM-DD HH:MM local, from <column>)`, naming the column it came from. Claim only what you're about to start. Claim at the end of the line, never as a leading `[word]` (the board dashboard reads that as a role).
- **Respect claims:** never work on an item another alias has claimed. If a claim looks abandoned, ask the user before taking it over.
- **PR open:** once the item's PR is open, keep it in Now with the claim and add the PR number (` — PR #N, awaiting merge`), so no other session picks it up while it waits.
- **Release:** the work ships when its PR is merged. Then move the item to Done per the usual one-line note, with the PR number, without the claim. Whichever session sees a merged PR first (or the user) does this. If you stop before finishing, remove the claim, put the item back in the column it came from, and add a short note of where it stands.
- **Subagents** work under the claim of the session that spawned them; they don't claim items themselves.

## Landing work: branches and pull requests

Each session works on its own branch in a worktree (`<alias>/<short-slug>`) and lands it through a pull request, so sessions never share unpushed commits on `main`. This replaces any general instruction to land work by fast-forwarding `main` and pushing it:

1. Work and commit on the branch. Never commit to `main` locally; it only moves by `git pull --ff-only` after a merge.
2. Before the first push, rebase the branch on `origin/main`. After it's pushed, bring in new `main` commits with `git merge origin/main` instead (no force pushes).
3. Run `/pre-push`: it reviews the branch, pushes it (`git push -u origin <branch>`), opens the PR (`gh pr create --body-file`), and marks the board item ` — PR #N, awaiting merge`.
4. Stop there. Rachel reviews and squash-merges the PR on GitHub; agents never merge (`gh pr merge` is denied) and never push `main`. The hook also denies `gh pr update-branch` and `gh repo sync`, which move branches on GitHub, and `gh workflow run`, which can start the pipeline (it commits to `main`).
5. After the merge: `git pull --ff-only` on `main` in the main checkout, remove the worktree, `git branch -D` the branch (a squash merge leaves its commits off `main`, so `-d` refuses), and move the item to Done.

While a session is in its worktree, Claude Code refuses commands it can't verify stay inside that worktree, and the auto-mode classifier blocks chained commits. So run each git command on its own, from the worktree root: no `cd`, no `git -C` into another worktree or the main checkout, and no `&&`/`;` chains or subshells around git. Create or append to files with Write/Edit, not `cat >> file <<EOF`, and commit with `git commit -F <file in the scratchpad>`. `/pre-push`'s command that records the review is allowed as is: run it exactly as the skill gives it, and only after the review has run. From the main checkout (before entering a worktree or after leaving it), `git -C` to read other worktrees is fine, as `/pick` does.

The hourly pipeline is the one exception: its GitHub Actions job commits data directly to `main`, and only runs on `main`. A GitHub ruleset blocks force pushes to and deletion of `main`, but doesn't require PRs (that would block the data job); the push hooks enforce the PR flow for agents. The repo allows squash merges only, and deletes a PR's branch once it's merged.

### Two review layers

Each review has its own job, so the second finds different things instead of repeating the first:

- **`/pre-push` (before the push, Sonnet):** the public-repo checklist (secrets, personal info, neutrality) and per-commit correctness and security. It must come first: once a branch is pushed, it's public.
- **PR review (`.github/workflows/pr-review.yml`, Sonnet):** runs once per PR from this repo, when it is opened, reopened or marked ready (drafts and forks skipped; later pushes aren't re-reviewed, to limit usage). It reviews the squashed change merged into the current `main` (collisions with other sessions' merged work), using CLAUDE.md and STYLE.md as the rubric, plus missing tests and stale docs. It posts only findings it's confident about, as inline comments; it can't push, approve, or edit. Its run summary is on the Actions run page, with the run's token usage (it runs on the Claude subscription, so reviews count against plan limits).

Handle PR review findings like pre-push ones (`/pre-push` step 3): propose fixing, filing or dropping each, and act once the user agrees.

## Model choice

Subagents get the cheapest model that can do the job. Always pass `model` when spawning one.

- **Sonnet:** reviews and research that read a lot and report back (the pre-push code and security reviews, broad investigations). The main session checks their findings, so they don't need Opus.
- **Haiku:** file and code search with no judgment calls (`Explore`, "where is X used").
- **Opus (inherit, no override):** agents that write or change code, and anything where a wrong answer ships unseen.

Long sessions cost more per turn as context grows: start a new session (`/clear`) when switching to an unrelated board item.

## Public repo: review before every push

This repository is public, and a pushed branch or PR is public as soon as it's pushed or opened. Before any `git push`, review every outgoing commit individually (`git log -p --cc origin/main..HEAD`, including commit messages and merge commits), and the PR title and body, not just the net diff. A secret added in one commit and removed in a later one is still published with the history. Report findings to the user. Do not push until the user confirms.

The same goes for any text posted to GitHub: PR titles and descriptions (and later edits to them), PR comments, review comments and replies, and issues. Write the text to a file (in the scratchpad), run this checklist over it, show it to the user, and post it from the file with the gh command alone: `gh pr comment <N> --body-file <file>` (likewise pr/issue create, edit, review), or for a review-comment reply `gh api repos/<owner>/<repo>/pulls/<N>/comments/<id>/replies -F body=@<file>`. The push hook asks before these and shows the whole text; it denies every other way of posting (inline text, stdin, `--fill`, templates, editors, every other `gh api` write, closing with a comment, gh aliases, a post chained with other commands, flags before the action (`gh pr -b x comment`), `gh pr revert`, and any of `` ` `` `$ \ * ? [ ] { } ~ !` or a line break in the command, so word titles without them; gh's literal `{owner}` and `{repo}` placeholders are the one exception). The body file can be at most 20,000 bytes, so the prompt shows it in full. Separately, the hook denies any Bash command over 20,000 characters, posting or not. `/pre-push` covers a PR's opening title and body; for a comment or a description edit later, run the checklist on its own. Releases, gists, labels, projects and the repo description aren't gated by the hook, and neither is gh run from a script or another program (the hook reads command text, so it guards against accidents, not evasion); the checklist applies to all of them too.

Because the hook reads command text, it also refuses harmless commands: any command that contains push anywhere, even inside another word (`pre-push`, `confirm-push.py`), along with `--no-verify` or `hooksPath`, and any command with `$'...'` quoting that contains the word git or gh anywhere (a path like `/usr/bin/gh` too, but not `github` or `high`), or an escape Python can't decode (`\U` above `10FFFF`, or `\x`, `\u` or `\U` with no hex digit after it), with or without git or gh. A grep of the hook's own source often trips this. The push hook, its tests and its git hook live in the maintainer's shared setup, outside this repo; read them with Read/Grep, not Bash.

Check for:

- **Secrets:** API keys, tokens, app passwords, `.env` files, credentials in URLs, logs, or test fixtures.
- **Personal info:** personal emails, home directory paths (e.g. `/Users/...`), machine names, IPs, or anything about the maintainer beyond "Rachel Sprague" and rachelsprague.com. No links to personal (non-professional) accounts or sites.
- **Commit identity:** author email must be the GitHub noreply address, not a personal email.
- **Neutrality:** code comments, commit messages, test data, and docs must be free of opinions about legislators, parties, or policies. Same standard as STYLE.md.
- **Internal notes:** TODOs or comments that wouldn't read well in public, scratch files, debug output.
- **Data and size:** no large raw data dumps committed by accident; respect `.gitignore`.
- **Third-party content:** nothing copied in that isn't public domain or properly licensed.

## Site build notes

- **Member portraits:** use official congressional portraits from the `unitedstates/images` project, keyed by bioguide ID (already in our member data). Same crop, size, and treatment for every member. Fall back to initials when a member has no portrait yet (common for new members).
