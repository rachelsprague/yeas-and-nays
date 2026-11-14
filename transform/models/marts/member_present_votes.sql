{#-
  One row per member who answered Present at least once this Congress: how
  many roll calls they answered Present on.
-#}

select
    bioguide_id,
    count(*) as present_votes
from {{ ref('positions') }}
where position = 'present'
group by bioguide_id
