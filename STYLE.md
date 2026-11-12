# Yeas & Nays — Style Guide

Yeas & Nays reports recorded votes in the U.S. House and Senate. It states what happened, sourced from official records, and nothing more. Every post and page follows these rules regardless of party, topic, or outcome.

## Voice

- **State the facts:** result, tally, date, and source. Nothing else.
- **No adjectives or characterization.** Never "narrowly," "controversial," "sweeping," "slammed," "historic," "bipartisan win," etc.
- **Use official language.** Quote the vote question and measure title as the Clerk or Senate records them. Don't paraphrase what a bill "does."
- **Party breaks are counts, not judgments.** "Voted against party majority: …" Never "broke ranks," "defied," or "crossed the aisle."
- **One template for every vote.** The same structure applies whichever party wins or what the topic is.
- **Always link the source.** Every post links the official vote record (or our vote page, which links the official record).
- **Names as officially listed,** with party and state: `Murkowski (R-AK)`. House members include district: `Lawler (R-NY-17)`.
- **Use the chamber's own terms.** House: "Yea / Nay" or "Aye / No" as recorded. Senate: "Yea / Nay." Always include "Present" and "Not Voting" counts on the site; in posts, include them only when nonzero.
- **No emoji, hashtags, or calls to action** ("contact your rep," "share this").
- **No commentary from the account.** It does not reply, quote-post, or repost others.

## Post rules (Bluesky bot)

### Which votes get posted

| Post | Skip (site only) |
| --- | --- |
| Passage of bills and joint/concurrent resolutions | Rules (H.Res. providing for consideration) |
| Nominations (confirmations) | Motions to recommit |
| Cloture | Motions to table, adjourn, or reconsider |
| Veto overrides | Quorum calls |
| Conference reports | Journal approval |
| Constitutional amendments | Amendments, unless agreed to on a major bill |
| Suspension votes that pass | Procedural motions generally |

Unsure? Default to **skip** on the bot; everything still appears on the site.

### Post template

```
{Chamber} {result verb} {official title or nominee + position}
{Yea} Yea · {Nay} Nay{ · tie-break note if VP voted}
Voted against party majority: {Name (P-ST)}, {Name (P-ST)}, … and {N} others
{link}
```

- **Result verbs:** passes / fails / confirms / rejects / invokes cloture on / fails to invoke cloture on / overrides veto of / sustains veto of. Use the official result text when in doubt.
- **Party-break line:** include only when at least one member voted against their party's majority. List up to 5 names, then "and N others." Independents are grouped with the party they caucus with for this calculation, and the post says so on the site's methodology page.
- **Length:** Bluesky posts max out at 300 characters. Truncate long titles with "…" before dropping the tally or link.

### Example (format only)

```
Senate confirms {Nominee} as {Position}
51 Yea · 50 Nay (Vice President voted to break tie)
Voted against party majority: {Name (R-ME)}, {Name (R-AK)}, {Name (R-KY)}
senate.gov/legislative/LIS/roll_call_votes/...
```

### Pacing

- Post each vote once. Track the last posted vote ID per chamber so nothing double-posts.
- During high-volume days (e.g., vote-a-ramas), post at most one vote every ~10 minutes, in order.
- If source data is later corrected, update the site; do not delete or repost on Bluesky unless the original post was factually wrong.
