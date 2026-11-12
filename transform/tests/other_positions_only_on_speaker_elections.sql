-- 'other' is for candidate names in an Election of the Speaker. Anywhere else
-- it means a position value the normalize_position macro doesn't know yet.
select positions.vote_id, positions.position_raw, count(*) as n
from {{ ref('positions') }} as positions
inner join {{ ref('votes') }} as votes on votes.vote_id = positions.vote_id
where positions.position = 'other'
  and votes.question <> 'Election of the Speaker'
group by all
