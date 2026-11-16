-- Each bill or resolution has at most one latest roll call, so joining to it
-- can't repeat a sponsored or cosponsored bill.
select congress, bill_type, bill_number, count(*) as n
from {{ ref('int_latest_vote_per_bill') }}
group by congress, bill_type, bill_number
having count(*) > 1
