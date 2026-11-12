with source as (
    select * from {{ source('staged', 'house_positions') }}
)

select
    'h' || congress || '-' || regexp_extract(session, '^(\d+)', 1) || '-' || lpad(rollcall_num, 4, '0') as vote_id,
    bioguide_id,
    vote as position_raw,
    {{ normalize_position('vote') }} as position,
    party as party_as_recorded,
    state as state_as_recorded,
    name as name_as_recorded
from source
