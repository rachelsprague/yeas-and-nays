{#-
  One row per vote per caucus (R, D): how the caucus split on yes/no, and its
  majority position. Present and Not Voting are not counted. When yes and no
  are tied (including 0-0, e.g. quorum calls and Speaker elections), the
  caucus has no majority position and majority_position is null.
-#}

select
    vote_id,
    caucus_party,
    count(*) filter (where position = 'yes') as yes_count,
    count(*) filter (where position = 'no') as no_count,
    case
        when count(*) filter (where position = 'yes') > count(*) filter (where position = 'no') then 'yes'
        when count(*) filter (where position = 'no') > count(*) filter (where position = 'yes') then 'no'
    end as majority_position
from {{ ref('int_positions_resolved') }}
where caucus_party is not null
group by vote_id, caucus_party
