-- The site labels a Speaker election's result "Most votes: …", so the
-- recorded result must be the candidate (or one of those tied) with the most
-- votes among the positions.
with counts as (
    select vote_id, position_raw, count(*) as n
    from {{ ref('positions') }}
    where position = 'other'
    group by all
),

top as (
    select vote_id, max(n) as top_n
    from counts
    group by vote_id
)

select votes.vote_id, votes.result, counts.n as result_n, top.top_n
from {{ ref('votes') }} as votes
left join top on top.vote_id = votes.vote_id
left join counts on counts.vote_id = votes.vote_id and counts.position_raw = votes.result
where votes.question = 'Election of the Speaker'
  and counts.n is distinct from top.top_n
