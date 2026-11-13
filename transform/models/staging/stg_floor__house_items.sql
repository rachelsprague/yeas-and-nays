select
    cast(congress as integer) as congress,
    cast(week_date as date) as week_date,
    category,
    cast(category_order as integer) as category_order,
    item_id,
    cast(item_order as integer) as item_order,
    legis_num as measure_number,
    bill_type,
    bill_number,
    floor_text as title,
    cast(add_date as timestamp) as added_at,
    cast(remove_date as timestamp) as removed_at,
    source_file
from {{ source('staged', 'house_floor_items') }}
