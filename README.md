# yeas-and-nays

Open data pipeline for U.S. congressional roll call votes. Powers the Yeas &amp; Nays Bluesky bot and yeasandnaysdata.com.

Covers the 119th Congress (2025–2027): every House and Senate roll call vote, every member's position, and whether each member voted with or against their party's majority.

## Pipeline

```
make all      # ingest -> stage -> model -> export
```

| Step | Command | What it does |
| --- | --- | --- |
| Ingest | `make ingest` | Downloads House Clerk roll call XML, Senate roll call XML, [congress-legislators](https://github.com/unitedstates/congress-legislators) member data, and, from the [Congress.gov API](https://api.congress.gov/), bill details (sponsor, cosponsors), Congressional Research Service summaries, each bill's actions (for its path from introduction to law), and the bills each member introduced, plus the House and Senate floor schedules, into `data/raw/` (gitignored). Incremental: re-fetches only the most recent votes to pick up corrections, and summaries for recently voted bills or once a week. The Congress.gov step needs `CONGRESS_API_KEY`; without it that step is skipped. |
| Stage | `make stage` | Parses raw files into flat Parquet under `data/staged/` (gitignored). Values kept as recorded. |
| Model | `make model` | `dbt build` in `transform/`: builds DuckDB models and runs unit and data tests. |
| Export | `make export` | Writes JSON from the marts into `data/out/` (committed). |

Requires [uv](https://docs.astral.sh/uv/). Python, site plugin and site JS tests: `make test`, with Node 22.22 or later for the JS tests (CI runs them on every PR and push to `main`). Changes land through pull requests after a pre-push review; `.claude/pre-push.md` sets this repo's review focus.

## Sources

- **House:** Office of the Clerk, `clerk.house.gov/evs/{year}/rollNNN.xml`
- **Senate:** `senate.gov/legislative/LIS/roll_call_votes/`
- **Members:** `unitedstates/congress-legislators` (current and historical), the YAML files on its `main` branch
- **Floor schedules:** House Majority Leader's weekly schedule, `docs.house.gov/floor/` (this week and next); Senate session days (`senate.gov/legislative/schedule/floor_schedule.xml`) and daily floor activity (`senate.gov/legislative/LIS/floor_activity/`, last 10 session days), read for cloture motions filed and voted on; the House Clerk's floor proceedings for the latest legislative day (`clerk.house.gov/floor/`), read for when the House convened and next convenes
- **District map:** Census Bureau congressional district boundaries (119th: cartographic boundary file `cb_2024_us_cd119_500k`; 120th: 2026 TIGER/Line `tl_2026_{state}_cd120`), place boundaries (`cb_2024_us_place_500k`) and 2024 city and town population estimates; see `scripts/build_district_map.py`
- **ZIP code search:** Census Bureau ZIP Code Tabulation Area to block relationship file (`tab20_zcta520_tabblock20_natl`) and block equivalency files for each Congress's districts (`NationalCD119`, `NationalCD120`), checked against the 119th ZCTA-to-district relationship file (`tab20_cd11920_zcta520_natl`); see `scripts/build_zip_lookup.py`
- **Bills:** Congress.gov API, `/bill/{congress}/{type}/{number}`, `.../summaries`, `/member/{bioguide_id}/sponsored-legislation`, and `/member/{bioguide_id}/cosponsored-legislation` (key sent as the `X-Api-Key` header)

## Models

| Model | Grain | Key |
| --- | --- | --- |
| `members` | one row per member who served in a Congress on the site (`seeds/congresses.csv`), with their last one | `bioguide_id` |
| `votes` | one row per roll call vote | `vote_id`, e.g. `h119-1-0042`, `s119-2-0107` |
| `positions` | one row per member per vote | `vote_id` + `bioguide_id` |
| `bills` | one row per bill or resolution with a recorded vote: sponsor, introduced date, cosponsor count | `bill_id`, e.g. `119-hr-1013` |
| `sponsored_bills` | one row per bill or resolution a member introduced in a Congress on the site, with its latest action and latest roll call | `bioguide_id` + `bill_id` |
| `sponsored_lists` | one row per member per Congress whose sponsored list has been fetched (a failed fetch leaves none) | `bioguide_id` + `congress` |
| `cosponsored_bills` | one row per bill or resolution a member cosponsored in a Congress on the site, with its latest action and latest roll call | `bioguide_id` + `bill_id` |
| `cosponsored_lists` | one row per member per Congress whose cosponsored list has been fetched (lists fill in over several runs) | `bioguide_id` + `congress` |
| `vote_summaries` | one row per vote on a bill with a CRS summary: the summary of the version in effect on the vote date | `vote_id` |
| `bill_milestones` | one row per bill or resolution with a recorded vote per step it has reached toward law (introduced, committee, passed or failed in each chamber, differences, President, veto, override, law), with its dates, from Congress.gov actions and this site's roll calls | `milestone_id`, e.g. `119-hr-1:passed_house` |
| `member_stats` | one row per member per Congress with a recorded position: roll calls, votes cast, missed votes %, voted with party majority % | `bioguide_id` + `congress` |
| `member_congresses` | one row per member per Congress on the site they served in or voted in: dates of service and `member_stats` | `bioguide_id` + `congress` |
| `floor_schedule` | one row per item that may come up for a vote: House weekly schedule items (removed items dropped) and Senate cloture motions filed but not yet voted on, each with the roll call that followed, if any | `item_id`, e.g. `h-2026-11-16-409831`, `s-pn1272-3`, `s-h-r-2347-measure` |
| `senate_sessions` | one row per time the Senate convened this session, with when it's set to convene next and whether that's a pro forma session | `convene_time_et` |
| `house_floor_days` | the House's latest legislative day: when it convened, whether it has adjourned, and when it next convenes | `legislative_day` |

**Joining members across chambers.** House records carry the Bioguide ID. Senate records carry an LIS member ID, which is mapped to the Bioguide ID through congress-legislators. Party and caucus are taken from the term (or, for a mid-term party change, the affiliation period) in effect on the vote date.

**Voted against party majority.** For each vote, each caucus's majority position is whichever of yes/no more of its members cast; Present and Not Voting are not counted. Independents are grouped with the party they caucus with. `voted_against_party_majority` is true when a member voted yes/no opposite to their caucus majority, false when with it, and null when it doesn't apply (the member didn't vote yes/no, the caucus was tied, or the vote wasn't a yes/no question, such as an Election of the Speaker).

## Output (`data/out/`)

| File | Contents |
| --- | --- |
| `meta.json` | Vote and member counts, latest roll number per chamber, Congress and session |
| `members.json` | All members, with their stats for their last Congress and `congresses`: dates and stats for each Congress, newest first |
| `members/{bioguide_id}.json` | One member: the bills and resolutions they introduced and cosponsored, one group per Congress, newest first (each is null until a list is first fetched) |
| `floor_schedule.json` | `floor_schedule` items with display labels, when the Senate next convenes, and each chamber's floor status (when it convened if it hadn't adjourned, else when it next convenes), for the home page's floor band |
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

Each post ends with a link to the vote's page on the site and carries a link card for that page. The bot builds the card from the page's Open Graph title, description and image, as the Bluesky app does when you paste a URL (`src/yan/bot/card.py`). If the card or its image can't be read, the post goes out without one and the run logs a warning.

## Site

`site/` is a Jekyll site that reads `data/out/` directly (`site/_plugins/yan_data.rb`) and generates a page per vote (`/votes/{congress}/{chamber}/{session}/{roll}/`) and per member (`/members/{bioguide_id}/`), plus the home page, the vote and member indexes, and About. The plugin only joins and arranges the pipeline's data; every count and definition comes from the models above. Filters are plain JavaScript over rows already in the page, so everything is readable without it. Colors come from `site/assets/css/tokens.css`; brand assets are linked from `brand/`.

`/find/` is a map of every House district, each paired with its current representative. The shapes, city labels and each district's largest cities and towns are prebuilt into `site/_maps/{congress}.json` by `uv run scripts/build_district_map.py`, run again only when district lines change; the site draws the map for the Congress in `data/out/meta.json`, so the 120th Congress lines take over when its members do. The script can keep a state's 119th lines for the 120th where the Census Bureau's 2026 file doesn't match the plan used in the 2026 election (`KEEP_119`; empty since Missouri's file was updated). The map scripts pin their libraries in a `.py.lock` file next to them.

The page's ZIP code search runs in the browser from `site/assets/maps/zip-{congress}.json`, built by `uv run scripts/build_zip_lookup.py` from Census files that place each census block in a ZIP Code Tabulation Area (ZCTA) and in a district. A ZCTA lists every district it has land in, so a split ZIP code shows all its districts and the reader chooses; the page never picks one. The Census Bureau publishes its own ZCTA-to-district file only for the 119th Congress, so the script builds both Congresses the same way and stops unless its 119th result matches that file exactly, and unless each Congress's districts are the map's. Run it after `build_district_map.py`.

`/search/` searches the whole site with [Pagefind](https://pagefind.app), a static index built from the finished pages after `jekyll build` (pinned in `site/package-lock.json`). Each page is indexed under a "Show" label (`search_type` in its front matter; `search: false` leaves it out), and long lists such as a vote's roll call are marked `data-pagefind-ignore` so a member's name doesn't match every vote. `make site-serve` has no index, so its search page says search isn't available.

Explainer pages (How things work) can end with a house ad for one of the maker's other projects: `house_ad: true` in front matter adds the slot from `site/_includes/house-ad.html` at the end of `<main>`, with its stylesheet `site/assets/css/house-ads.css`. Every unit is in the page; a short inline script shows one at random per visit (the first without JavaScript). They are links only, with no third-party scripts, and never appear on vote, member or other data pages, which a test checks. KeepScore's copy is `site/_data/house_ad_keepscore.json`. About has a "Who built this" card of the same projects instead.

Each vote page's map (By district on House votes, By state on Senate votes; each House district, or each senator's half of a state, filled with their vote) draws from a lighter copy of those shapes: `uv run scripts/build_vote_map.py` simplifies `site/_maps/{congress}.json` into `site/assets/maps/{congress}.json`, which the browser fetches once and caches. Run it after `build_district_map.py`. Only votes in the Congress of `data/out/meta.json` get the map, since members' districts are as of that Congress; every vote keeps the by-state table.

Every page has Open Graph and Twitter card tags for link previews. A vote page's card image shows its official title, result and tally, drawn by `yan cards` (`src/yan/cards.py`, with Pillow and the brand fonts in `src/yan/fonts/`) into `site/assets/cards/{vote_id}.png` before each build; the cards aren't committed. Quorum calls and Speaker elections, which have no Yea or Nay, use the brand card `brand/social/og-card-1200x630.png`, as every other page does.

```
make site-serve   # build and serve at http://localhost:4000 (needs Ruby and Bundler)
make site-search  # same, plus the search index, so /search/ works (also needs Node)
```

## Automation

`.github/workflows/pipeline.yml` runs hourly, started by an external scheduler (cron-job.org) through the workflow_dispatch API, and on demand: ingest → stage → `dbt build` → export → bot, then commits changes to `data/out/` and the bot state back to `main`. A failing dbt test stops the run before export and the bot. The steps that run third-party code get a read-only token; a separate `commit` job, which runs none, takes their output as an artifact and is the only one that can push. Before committing, it checks the artifact with `scripts/check_data_artifact.py` (standard library only): only the files export writes, size caps, valid JSON, and bot state that never moves back to an earlier vote. The raw-data cache is saved even when a later step fails, so a retry picks up where ingest left off.

| Setting | Type | Purpose |
| --- | --- | --- |
| `BOT_PUBLISH` | repository variable | `true` to publish to Bluesky. Unset or anything else: dry run, posts printed to the log. |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | `pipeline` environment secrets | Bluesky account; passed to the bot step only when publishing. |
| `CONGRESS_API_KEY` | `pipeline` environment secret | Congress.gov API key for bill details and summaries; passed to the ingest step only. |

The `pipeline` environment's deployment branches are limited to `main`, so a run from any other branch can't read its secrets.

`.github/workflows/site.yml` builds the site and deploys it to GitHub Pages after each successful data run, and on pushes that change `site/`. Pages must be set to deploy from GitHub Actions.

`.github/workflows/test.yml` runs `pytest` and the site plugin tests on every pull request and push to `main`. dbt tests run in the hourly data job.
