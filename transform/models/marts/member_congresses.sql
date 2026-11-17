{#-
  One row per member per Congress on the site (the congresses seed) that they
  served in or are recorded on a roll call in: their dates of service in that
  Congress and their vote stats for it (member_stats). A member listed on a
  roll call without a term in that Congress (e.g. a member-elect on the
  opening quorum call who never took the seat) has stats but no dates.
-#}

with periods as (
    select * from {{ ref('int_member_periods') }}
),

congresses as (
    select * from {{ ref('congresses') }}
),

stats as (
    select * from {{ ref('member_stats') }}
),

-- A member's periods in a Congress, across chambers, clipped to its dates.
service as (
    select
        periods.bioguide_id,
        congresses.congress,
        greatest(min(periods.period_start), congresses.start_date) as served_from,
        least(max(periods.period_end), congresses.end_date) as served_to
    from periods
    inner join congresses
        on periods.period_end > congresses.start_date
        and periods.period_start < congresses.end_date
    group by periods.bioguide_id, congresses.congress, congresses.start_date, congresses.end_date
),

member_congress as (
    select bioguide_id, congress from service
    union
    select bioguide_id, congress from stats
)

select
    member_congress.bioguide_id,
    member_congress.congress,
    service.bioguide_id is not null as served_in_congress,
    service.served_from,
    service.served_to,
    stats.* exclude (bioguide_id, congress)
from member_congress
left join service using (bioguide_id, congress)
left join stats using (bioguide_id, congress)
