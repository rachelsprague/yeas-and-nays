# yeas-and-nays

Open data pipeline for U.S. congressional roll call votes. Powers the Yeas &amp; Nays Bluesky bot and yeasandnaysdata.com.

Covers the 119th Congress (2025–2027): every House and Senate roll call vote, every member's position, and whether each member voted with or against their party's majority.

## Pipeline

```
make all      # ingest -> stage -> model -> export
```

| Step | Command | What it does |
| --- | --- | --- |
| Ingest | `make ingest` | Downloads House Clerk roll call XML, Senate roll call XML, and [congress-legislators](https://github.com/unitedstates/congress-legislators) member data into `data/raw/` (gitignored). Incremental: re-fetches only the most recent votes to pick up corrections. |
| Stage | `make stage` | Parses raw files into flat Parquet under `data/staged/` (gitignored). Values kept as recorded. |
| Model | `make model` | `dbt build` in `transform/`: builds DuckDB models and runs unit and data tests. |
| Export | `make export` | Writes JSON from the marts into `data/out/` (committed). |

Requires [uv](https://docs.astral.sh/uv/). Parser tests: `make test`.

## Sources

- **House:** Office of the Clerk, `clerk.house.gov/evs/{year}/rollNNN.xml`
- **Senate:** `senate.gov/legislative/LIS/roll_call_votes/`
- **Members:** `unitedstates/congress-legislators` (current and historical)

## Models

| Model | Grain | Key |
| --- | --- | --- |
| `members` | one row per member who served in the 119th Congress | `bioguide_id` |
| `votes` | one row per roll call vote | `vote_id`, e.g. `h119-1-0042`, `s119-2-0107` |
| `positions` | one row per member per vote | `vote_id` + `bioguide_id` |

**Joining members across chambers.** House records carry the Bioguide ID. Senate records carry an LIS member ID, which is mapped to the Bioguide ID through congress-legislators. Party and caucus are taken from the term (or, for a mid-term party change, the affiliation period) in effect on the vote date.

**Voted against party majority.** For each vote, each caucus's majority position is whichever of yes/no more of its members cast; Present and Not Voting are not counted. Independents are grouped with the party they caucus with. `voted_against_party_majority` is true when a member voted yes/no opposite to their caucus majority, false when with it, and null when it doesn't apply (the member didn't vote yes/no, the caucus was tied, or the vote wasn't a yes/no question, such as an Election of the Speaker).

## Output (`data/out/`)

| File | Contents |
| --- | --- |
| `meta.json` | Vote and member counts, latest roll number per chamber and session |
| `members.json` | All members |
| `votes.json` | All votes: metadata, official tallies, source links, newest first |
| `votes/{vote_id}.json` | One vote: metadata, totals by party, caucus majority positions, members who voted against their party majority, and every member's position as recorded |

Output is deterministic: re-running with no new votes produces no diff.

## Bot (dry run)

The Bluesky bot reads `data/out/` and applies the post rules in [STYLE.md](STYLE.md). It only prints posts; publishing isn't built yet.

```
uv run yan bot preview -n 10 [--vote ID]   # the 10 most recent postable votes
uv run yan bot run                          # votes not yet handled, per data/bot/state.json
uv run yan bot init                         # start from the latest vote
```

State (`data/bot/state.json`, committed) records the last vote handled per chamber, posted or skipped, so a vote is never posted twice. A dry run never advances it.
