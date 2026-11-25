{#-
  One row per bill or resolution with a recorded vote this Congress, from
  Congress.gov: who introduced it (the sponsor), when, and how many
  cosponsors it has.

  The sponsor's party and seat are those on the day the measure was introduced,
  from the member's period in the chamber it was introduced in. If no period
  covers that day (dates in the two sources can disagree), the nearest one is
  used, as for positions (int_positions_resolved).
-#}

with bills as (
    select
        *,
        case when bill_type like 'h%' then 'house' else 'senate' end as introduced_chamber
    from {{ ref('stg_congress_gov__bills') }}
),

periods as (
    select * from {{ ref('int_member_periods') }}
)

select
    bills.congress,
    bills.bill_type,
    bills.bill_number,
    bills.congress || '-' || bills.bill_type || '-' || bills.bill_number as bill_id,
    bills.title,
    bills.introduced_date,
    bills.origin_chamber,
    bills.sponsor_bioguide_id,
    bills.sponsor_full_name,
    periods.party as sponsor_party,
    periods.chamber as sponsor_chamber,
    periods.state as sponsor_state,
    periods.district as sponsor_district,
    bills.cosponsor_count,
    bills.policy_area,
    {{ congress_gov_url('bills.congress', 'bills.bill_type', 'bills.bill_number') }} as congress_gov_url,
    bills.legislation_url,
    bills.updated_at
from bills
left join periods
    on periods.bioguide_id = bills.sponsor_bioguide_id
    and periods.chamber = bills.introduced_chamber
-- Period boundaries can share a day; among those take the latest start.
qualify row_number() over (
    partition by bills.congress, bills.bill_type, bills.bill_number
    order by
        (bills.introduced_date between periods.period_start and periods.period_end) desc nulls last,
        least(abs(datediff('day', periods.period_start, bills.introduced_date)),
              abs(datediff('day', periods.period_end, bills.introduced_date))) asc nulls last,
        periods.period_start desc
) = 1
