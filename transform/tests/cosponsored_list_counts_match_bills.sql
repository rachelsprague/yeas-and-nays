-- Each fetched cosponsored list's bill_count equals the member's rows in
-- cosponsored_bills, and every cosponsored bill belongs to a fetched list.
with counted as (
    select bioguide_id, congress, count(*) as n
    from {{ ref('cosponsored_bills') }}
    group by bioguide_id, congress
)

select
    coalesce(lists.bioguide_id, counted.bioguide_id) as bioguide_id,
    coalesce(lists.congress, counted.congress) as congress,
    lists.bill_count,
    counted.n
from {{ ref('cosponsored_lists') }} as lists
full outer join counted
    on counted.bioguide_id = lists.bioguide_id
    and counted.congress = lists.congress
where lists.bioguide_id is null
   or lists.bill_count is distinct from coalesce(counted.n, 0)
