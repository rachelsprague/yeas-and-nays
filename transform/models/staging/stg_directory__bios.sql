select
    edition,
    cast(date_issued as date) as date_issued,
    state,
    chamber,
    district,
    printed_name,
    opening,
    education,
    professional_history,
    military_service
from {{ source('staged', 'directory_bios') }}
