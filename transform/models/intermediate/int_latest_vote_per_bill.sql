{#- The most recent roll call on each bill or resolution that has had one. -#}

select congress, bill_type, bill_number, vote_id, vote_date
from {{ ref('int_votes_unioned') }}
where bill_type is not null
qualify row_number() over (
    partition by congress, bill_type, bill_number
    order by vote_time_et desc, vote_id desc
) = 1
