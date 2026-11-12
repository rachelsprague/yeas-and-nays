with source as (
    select * from {{ source('staged', 'senate_positions') }}
)

select
    's' || congress || '-' || session || '-' || lpad(vote_number::integer::varchar, 4, '0') as vote_id,
    lis_member_id as lis_id,
    vote_cast as position_raw,
    {{ normalize_position('vote_cast') }} as position,
    party as party_as_recorded,
    state as state_as_recorded,
    member_full as name_as_recorded
from source
