select
    cast(congress as integer) as congress,
    bill_type,
    bill_number,
    title,
    cast(introduced_date as date) as introduced_date,
    origin_chamber,
    sponsor_bioguide_id,
    sponsor_full_name,
    cast(cosponsor_count as integer) as cosponsor_count,
    policy_area,
    legislation_url,
    cast(update_date as timestamp) as updated_at,
    source_file
from {{ source('staged', 'bills') }}
