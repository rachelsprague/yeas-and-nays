-- Grain of positions: one row per member per vote.
select vote_id, bioguide_id, count(*) as n
from {{ ref('positions') }}
group by vote_id, bioguide_id
having count(*) > 1
