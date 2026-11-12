-- The Congress.gov link we build from the bill type and number should be the
-- page Congress.gov itself reports for the bill.
select bill_id, congress_gov_url, legislation_url
from {{ ref('bills') }}
where legislation_url is not null
  and congress_gov_url <> legislation_url
