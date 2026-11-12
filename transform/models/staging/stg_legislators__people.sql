select
    bioguide_id,
    lis_id,
    first_name,
    last_name,
    official_full_name,
    is_current
from {{ source('staged', 'legislators') }}
