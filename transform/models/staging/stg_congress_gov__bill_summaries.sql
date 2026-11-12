select
    cast(congress as integer) as congress,
    bill_type,
    bill_number,
    version_code,
    cast(action_date as date) as action_date,
    action_desc,
    cast(update_date as timestamp) as updated_at,
    summary_html,
    source_file
from {{ source('staged', 'bill_summaries') }}
