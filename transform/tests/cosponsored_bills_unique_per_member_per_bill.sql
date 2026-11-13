-- A member cosponsors a given bill at most once.
select bioguide_id, bill_id, count(*) as n
from {{ ref('cosponsored_bills') }}
group by bioguide_id, bill_id
having count(*) > 1
