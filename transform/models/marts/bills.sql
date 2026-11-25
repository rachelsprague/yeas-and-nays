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
),

-- One row per sponsor, chamber and day, so the join below can't add or drop a
-- bill (a repeated one still fails the unique test on bill_id).
introductions as (
    select distinct sponsor_bioguide_id, introduced_chamber, introduced_date
    from bills
    where sponsor_bioguide_id is not null
),

sponsors as (
    select
        introductions.*,
        periods.party,
        periods.chamber,
        periods.state,
        periods.district
    from introductions
    left join periods
        on periods.bioguide_id = introductions.sponsor_bioguide_id
        and periods.chamber = introductions.introduced_chamber
    -- Period boundaries can share a day; among those take the latest start.
    qualify row_number() over (
        partition by
            introductions.sponsor_bioguide_id, introductions.introduced_chamber, introductions.introduced_date
        order by
            (introductions.introduced_date between periods.period_start and periods.period_end) desc nulls last,
            least(abs(datediff('day', periods.period_start, introductions.introduced_date)),
                  abs(datediff('day', periods.period_end, introductions.introduced_date))) asc nulls last,
            periods.period_start desc
    ) = 1
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
    sponsors.party as sponsor_party,
    sponsors.chamber as sponsor_chamber,
    sponsors.state as sponsor_state,
    sponsors.district as sponsor_district,
    bills.cosponsor_count,
    bills.policy_area,
    {{ congress_gov_url('bills.congress', 'bills.bill_type', 'bills.bill_number') }} as congress_gov_url,
    bills.legislation_url,
    bills.updated_at
from bills
left join sponsors
    on sponsors.sponsor_bioguide_id = bills.sponsor_bioguide_id
    and sponsors.introduced_chamber = bills.introduced_chamber
    and sponsors.introduced_date is not distinct from bills.introduced_date
