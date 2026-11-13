-- try_cast: a malformed value becomes null instead of failing the build (see stg_floor__house_items).
select
    try_cast(activity_date as date) as activity_date,
    try_cast(status_order as integer) as status_order,
    docnum,
    document_prefix,
    document_num,
    bill_type,
    bill_number,
    -- "Amendment to H.R. 2347" -> "H.R. 2347"; null unless the document is an amendment.
    regexp_replace(amends, '^Amendment to ', '') as amends,
    sponsor_name,
    document_title,
    status_text,
    source_file
from {{ source('staged', 'senate_floor_actions') }}
