select
    bioguide_id,
    cast(congress as integer) as congress,
    cast(bill_count as integer) as bill_count,
    source_file
from {{ source('staged', 'cosponsored_lists') }}
