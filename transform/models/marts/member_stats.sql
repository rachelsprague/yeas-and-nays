{#-
  One row per member with a recorded position this Congress: how often they
  voted, and how often their yes/no matched their caucus majority. Matches the
  definitions on the site's methodology page.

  The official record lists every sitting member on every roll call in their
  chamber (as Not Voting when absent), so a member's position rows are the
  roll calls held in their chamber while they were in office.

  - votes_cast: any recorded response other than Not Voting or Present (a
    candidate's name in a Speaker election counts as voting).
  - missed_votes_pct: (Not Voting + Present) / roll calls.
  - with_party_majority_pct: yes/no votes matching the caucus majority / all
    yes/no votes where the caucus had a majority. Null when there are none.
-#}

with positions as (
    select * from {{ ref('positions') }}
),

counts as (
    select
        bioguide_id,
        count(*) as roll_calls,
        count(*) filter (where position not in ('not_voting', 'present')) as votes_cast,
        count(*) filter (where position in ('not_voting', 'present')) as missed_votes,
        count(*) filter (where voted_against_party_majority is not null) as party_majority_votes,
        count(*) filter (where voted_against_party_majority = false) as with_party_majority_votes,
        count(*) filter (where voted_against_party_majority) as against_party_majority_votes
    from positions
    group by bioguide_id
)

select
    *,
    round(100.0 * missed_votes / roll_calls, 1) as missed_votes_pct,
    round(100.0 * with_party_majority_votes / nullif(party_majority_votes, 0), 1) as with_party_majority_pct
from counts
