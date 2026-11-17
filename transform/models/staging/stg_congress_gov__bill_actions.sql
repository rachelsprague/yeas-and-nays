select
    cast(congress as integer) as congress,
    bill_type,
    bill_number,
    cast(action_date as date) as action_date,
    action_code,
    action_type,
    source_system_code,
    action_text,
    source_file
from {{ source('staged', 'bill_actions') }}
