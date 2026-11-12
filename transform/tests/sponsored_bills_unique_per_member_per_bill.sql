-- A member sponsors a given bill at most once.
select bioguide_id, bill_id, count(*) as n
from {{ ref('sponsored_bills') }}
group by bioguide_id, bill_id
having count(*) > 1
