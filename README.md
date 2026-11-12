# yeas-and-nays

Open data pipeline for U.S. congressional roll call votes. Powers the Yeas &amp; Nays Bluesky bot and yeasandnaysdata.com.

Covers the 119th Congress (2025–2027): every House and Senate roll call vote, every member's position, and whether each member voted with or against their party's majority.

## Pipeline

```
make all      # ingest -> stage -> model -> export
```

| Step | Command | What it does |
| --- | --- | --- |
| Ingest | `make ingest` | Downloads House Clerk roll call XML, Senate roll call XML, [congress-legislators](https://github.com/unitedstates/congress-legislators) member data, and, from the [Congress.gov API](https://api.congress.gov/), bill details (sponsor, cosponsors), Congressional Research Service summaries, and the bills each member introduced into `data/raw/` (gitignored). Incremental: re-fetches only the most recent votes to pick up corrections, and summaries for recently voted bills or once a week. The Congress.gov step needs `CONGRESS_API_KEY`; without it that step is skipped. |
| Stage | `make stage` | Parses raw files into flat Parquet under `data/staged/` (gitignored). Values kept as recorded. |
| Model | `make model` | `dbt build` in `transform/`: builds DuckDB models and runs unit and data tests. |
| Export | `make export` | Writes JSON from the marts into `data/out/` (committed). |

Requires [uv](https://docs.astral.sh/uv/). Parser tests: `make test`. `make hooks` installs a git pre-push hook that refuses commits without a recorded pre-push review (`.claude/skills/pre-push/`).

## Sources

- **House:** Office of the Clerk, `clerk.house.gov/evs/{year}/rollNNN.xml`
- **Senate:** `senate.gov/legislative/LIS/roll_call_votes/`
- **Members:** `unitedstates/congress-legislators` (current and historical)
- **Bills:** Congress.gov API, `/bill/{congress}/{type}/{number}`, `.../summaries`, and `/member/{bioguide_id}/sponsored-legislation` (key sent as the `X-Api-Key` header)

## Models

| Model | Grain | Key |
| --- | --- | --- |
| `members` | one row per member who served in the 119th Congress | `bioguide_id` |
| `votes` | one row per roll call vote | `vote_id`, e.g. `h119-1-0042`, `s119-2-0107` |
| `positions` | one row per member per vote | `vote_id` + `bioguide_id` |
| `bills` | one row per bill or resolution with a recorded vote: sponsor, introduced date, cosponsor count | `bill_id`, e.g. `119-hr-1013` |
| `sponsored_bills` | one row per bill or resolution a member introduced this Congress, with its latest action and latest roll call | `bioguide_id` + `bill_id` |
| `vote_summaries` | one row per vote on a bill with a CRS summary: the summary of the version in effect on the vote date | `vote_id` |
| `member_stats` | one row per member with a recorded position: roll calls, votes cast, missed votes %, voted with party majority % | `bioguide_id` |

**Joining members across chambers.** House records carry the Bioguide ID. Senate records carry an LIS member ID, which is mapped to the Bioguide ID through congress-legislators. Party and caucus are taken from the term (or, for a mid-term party change, the affiliation period) in effect on the vote date.

**Voted against party majority.** For each vote, each caucus's majority position is whichever of yes/no more of its members cast; Present and Not Voting are not counted. Independents are grouped with the party they caucus with. `voted_against_party_majority` is true when a member voted yes/no opposite to their caucus majority, false when with it, and null when it doesn't apply (the member didn't vote yes/no, the caucus was tied, or the vote wasn't a yes/no question, such as an Election of the Speaker).

## Output (`data/out/`)

| File | Contents |
| --- | --- |
| `meta.json` | Vote and member counts, latest roll number per chamber and session |
| `members.json` | All members, with their `member_stats` |
| `members/{bioguide_id}.json` | One member: the bills and resolutions they introduced this Congress |
| `votes.json` | All votes: metadata, official tallies, source links, newest first |
| `votes/{vote_id}.json` | One vote: metadata, totals by party, caucus majority positions, members who voted against their party majority, and every member's position as recorded, and the CRS summary of the measure (HTML reduced to formatting tags), or null |

Output is deterministic: re-running with no new votes produces no diff.

## Bot

The Bluesky bot reads `data/out/` and applies the post rules in [STYLE.md](STYLE.md).

```
uv run yan bot preview -n 10 [--vote ID]   # the 10 most recent postable votes
uv run yan bot run                          # dry run: print posts for votes not yet handled
uv run yan bot run --publish                # post them and advance state
uv run yan bot init                         # start from the latest vote
```

State (`data/bot/state.json`, committed) records the last vote handled per chamber, posted or skipped, so a vote is never posted twice. A dry run never advances it. When publishing, the bot posts in order, one post every 10 minutes and at most 5 per run; skips anything its recent Bluesky posts already cover; and refuses to post a backlog older than 3 days (run `yan bot init` first).

## Site

`site/` is a Jekyll site that reads `data/out/` directly (`site/_plugins/yan_data.rb`) and generates a page per vote (`/votes/{congress}/{chamber}/{session}/{roll}/`) and per member (`/members/{bioguide_id}/`), plus the home page, the vote and member indexes, and About. The plugin only joins and arranges the pipeline's data; every count and definition comes from the models above. Filters are plain JavaScript over rows already in the page, so everything is readable without it. Colors come from `site/assets/css/tokens.css`; brand assets are linked from `brand/`.

```
make site-serve   # build and serve at http://localhost:4000 (needs Ruby and Bundler)
```

## Automation

`.github/workflows/pipeline.yml` runs hourly on weekdays (and on demand): ingest → stage → `dbt build` → export → bot, then commits changes to `data/out/` and the bot state back to `main`. A failing dbt test stops the run before export and the bot.

| Setting | Type | Purpose |
| --- | --- | --- |
| `BOT_PUBLISH` | repository variable | `true` to publish to Bluesky. Unset or anything else: dry run, posts printed to the log. |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | secrets | Bluesky account; passed to the bot step only when publishing. |
| `CONGRESS_API_KEY` | secret | Congress.gov API key for bill details and summaries; passed to the ingest step only. |

`.github/workflows/site.yml` builds the site and deploys it to GitHub Pages after each successful data run, and on pushes that change `site/`. Pages must be set to deploy from GitHub Actions.
