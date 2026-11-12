-- Official tallies on each vote must equal the counts rebuilt from positions.
-- Votes tallied by candidate (Election of the Speaker) have null tallies and are skipped.
with rebuilt as (
    select
        vote_id,
        count(*) filter (where position = 'yes') as yes_n,
        count(*) filter (where position = 'no') as no_n,
        count(*) filter (where position = 'present') as present_n,
        count(*) filter (where position = 'not_voting') as not_voting_n
    from {{ ref('positions') }}
    group by vote_id
)

select votes.vote_id, votes.yea_count, rebuilt.yes_n, votes.nay_count, rebuilt.no_n,
       votes.present_count, rebuilt.present_n, votes.not_voting_count, rebuilt.not_voting_n
from {{ ref('votes') }} as votes
left join rebuilt on rebuilt.vote_id = votes.vote_id
where votes.yea_count is not null
  and (
      votes.yea_count is distinct from rebuilt.yes_n
      or votes.nay_count is distinct from rebuilt.no_n
      or votes.present_count is distinct from rebuilt.present_n
      or votes.not_voting_count is distinct from rebuilt.not_voting_n
  )
