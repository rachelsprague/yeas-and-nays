{#-
  One row per member per vote.

  voted_against_party_majority is true when the member voted yes/no opposite
  to their caucus's majority, false when they voted with it, and null when it
  doesn't apply: the member answered Present / Not Voting / a candidate name,
  or their caucus had no majority position (a tie).
-#}

with positions as (
    select * from {{ ref('int_positions_resolved') }}
),

majority as (
    select * from {{ ref('int_caucus_majority') }}
)

select
    positions.vote_id,
    positions.bioguide_id,
    positions.chamber,
    positions.vote_date,
    positions.lis_id,
    positions.member_label,
    positions.position_raw,
    positions.position,
    positions.party_as_recorded,
    positions.state_as_recorded,
    positions.party,
    positions.caucus_party,
    positions.term_covers_vote_date,
    majority.majority_position as caucus_majority_position,
    case
        when positions.position in ('yes', 'no') and majority.majority_position is not null
            then positions.position <> majority.majority_position
    end as voted_against_party_majority
from positions
left join majority
    on majority.vote_id = positions.vote_id
    and majority.caucus_party = positions.caucus_party
