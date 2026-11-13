-- try_cast: a malformed value becomes null (and warns in the floor tests)
-- instead of failing the build, which would stop the hourly run.
select
    try_cast(congress as integer) as congress,
    try_cast(week_date as date) as week_date,
    category,
    try_cast(category_order as integer) as category_order,
    item_id,
    try_cast(item_order as integer) as item_order,
    legis_num as measure_number,
    bill_type,
    bill_number,
    floor_text as title,
    try_cast(add_date as timestamp) as added_at,
    try_cast(remove_date as timestamp) as removed_at,
    remove_date as removed_at_recorded,
    source_file
from {{ source('staged', 'house_floor_items') }}
