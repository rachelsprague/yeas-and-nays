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
- **Schedule:** GitHub Actions cron (weekday hourly): ingest → model → post → build/deploy.

## Secrets (GitHub Actions)

`BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `CONGRESS_API_KEY`. Never commit credentials or `.env` files. Send the Congress.gov key as an `X-Api-Key` header, not in URLs.

## Conventions

- Bot must support a dry-run mode that prints posts without publishing; default to dry run locally.
- Persist bot state (last posted vote ID per chamber) in the repo so runs are idempotent.
- Brand assets live in `brand/` (svg, social, favicon). Palette: aubergine #5A3463, paper #F2EFE6, ink #1C1C1C, dark-mode accent #A887B5. Type: Newsreader (display), IBM Plex Sans (UI/body).

## Backlog

Tracked locally, not in GitHub Issues: `BOARD.md` (one line per item) and `backlog/<slug>.md` for details. Both are gitignored because this repo is public. Don't create GitHub issues for this project.

## Public repo: review before every push

This repository is public. Before any `git push`, review every outgoing commit individually (`git log -p origin/main..HEAD`, including commit messages), not just the net diff. A secret added in one commit and removed in a later one is still published with the history. Report findings to the user. Do not push until the user confirms. Check for:

- **Secrets:** API keys, tokens, app passwords, `.env` files, credentials in URLs, logs, or test fixtures.
- **Personal info:** personal emails, home directory paths (e.g. `/Users/...`), machine names, IPs, or anything about the maintainer beyond "Rachel Sprague" and rachelsprague.com. No links to personal (non-professional) accounts or sites.
- **Commit identity:** author email must be the GitHub noreply address, not a personal email.
- **Neutrality:** code comments, commit messages, test data, and docs must be free of opinions about legislators, parties, or policies. Same standard as STYLE.md.
- **Internal notes:** TODOs or comments that wouldn't read well in public, scratch files, debug output.
- **Data and size:** no large raw data dumps committed by accident; respect `.gitignore`.
- **Third-party content:** nothing copied in that isn't public domain or properly licensed.

## Site build notes

- **Member portraits:** use official congressional portraits from the `unitedstates/images` project, keyed by bioguide ID (already in our member data). Same crop, size, and treatment for every member. Fall back to initials when a member has no portrait yet (common for new members).
