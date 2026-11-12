-- A bill has one sponsor, so it appears under at most one member.
select bill_id, count(distinct bioguide_id) as sponsors
from {{ ref('sponsored_bills') }}
group by bill_id
having count(distinct bioguide_id) > 1
