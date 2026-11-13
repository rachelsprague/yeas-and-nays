select
    bioguide_id,
    cast(congress as integer) as congress,
    bill_type,
    bill_number,
    title,
    cast(introduced_date as date) as introduced_date,
    cast(latest_action_date as date) as latest_action_date,
    latest_action_text,
    policy_area,
    source_file
from {{ source('staged', 'cosponsored_bills') }}
