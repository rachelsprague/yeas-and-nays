{#-
  One row per member who served in the 119th Congress, plus anyone the
  official record lists on a 119th roll call without a 119th term in
  congress-legislators (e.g. a member-elect listed on the opening quorum call
  who never took the seat). Chamber, state, district, party, and caucus
  reflect the member's most recent period of service; positions carry the
  values in effect on each vote's date.
-#}

with periods as (
    select * from {{ ref('int_member_periods') }}
),

in_congress as (
    select * from periods where overlaps_congress
),

recorded as (
    select distinct bioguide_id, chamber
    from {{ ref('int_positions_resolved') }}
    where bioguide_id is not null
),

-- Members on a 119th vote with no 119th term: their most recent period in that chamber.
recorded_only as (
    select periods.*
    from periods
    inner join recorded
        on recorded.bioguide_id = periods.bioguide_id
        and recorded.chamber = periods.chamber
    where periods.bioguide_id not in (select bioguide_id from in_congress)
    qualify row_number() over (partition by periods.bioguide_id order by periods.period_start desc) = 1
),

member_periods as (
    select * from in_congress
    union all
    select * from recorded_only
),

latest as (
    select *
    from member_periods
    qualify row_number() over (partition by bioguide_id order by period_start desc) = 1
),

service as (
    select
        bioguide_id,
        greatest(min(period_start), cast('{{ var("congress_start") }}' as date)) as served_from,
        least(max(period_end), cast('{{ var("congress_end") }}' as date)) as served_to
    from in_congress
    group by bioguide_id
),

people as (
    select * from {{ ref('stg_legislators__people') }}
)

select
    latest.bioguide_id,
    people.lis_id,
    people.first_name,
    people.last_name,
    people.official_full_name,
    latest.member_label,
    latest.chamber,
    latest.state,
    latest.district,
    latest.party,
    latest.caucus_party,
    -- Delegates and the Resident Commissioner vote only in the Committee of the Whole.
    latest.chamber = 'senate' or latest.state not in ('AS', 'DC', 'GU', 'MP', 'PR', 'VI') as is_voting_member,
    latest.overlaps_congress as served_in_congress,
    service.served_from,
    service.served_to,
    people.is_current
from latest
inner join people on people.bioguide_id = latest.bioguide_id
left join service on service.bioguide_id = latest.bioguide_id
