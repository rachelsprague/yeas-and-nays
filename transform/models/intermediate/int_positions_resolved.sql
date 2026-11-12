{#-
  One row per member per vote, with every position resolved to a bioguide ID
  and to the party/caucus in effect on the vote date.

  House records carry the bioguide ID directly. Senate records carry only the
  LIS member ID, which maps to bioguide through congress-legislators (id.lis).
  If a member can't be matched (e.g. a newly seated senator not yet in
  congress-legislators), bioguide_id is null and the relationships test on
  the positions mart fails, rather than the row being silently dropped.

  Party, caucus, and label come from the member's period covering the vote
  date. The official record occasionally lists a member outside the dates in
  congress-legislators (a member-elect who never took the seat on the opening
  quorum call; a departure dated a day early). Those positions are kept as
  recorded and matched to the member's nearest period in that chamber, with
  term_covers_vote_date = false.
-#}

with votes as (
    select vote_id, chamber, vote_date from {{ ref('int_votes_unioned') }}
),

house as (
    select
        vote_id, bioguide_id,
        null::varchar as lis_id,
        position_raw, position, party_as_recorded, state_as_recorded, name_as_recorded
    from {{ ref('stg_house__positions') }}
),

senate as (
    select
        positions.vote_id,
        people.bioguide_id,
        positions.lis_id,
        positions.position_raw, positions.position,
        positions.party_as_recorded, positions.state_as_recorded, positions.name_as_recorded
    from {{ ref('stg_senate__positions') }} as positions
    left join {{ ref('stg_legislators__people') }} as people
        on people.lis_id = positions.lis_id
),

positions as (
    select * from house
    union all
    select * from senate
),

periods as (
    select * from {{ ref('int_member_periods') }}
)

select
    positions.vote_id,
    votes.chamber,
    votes.vote_date,
    positions.bioguide_id,
    positions.lis_id,
    positions.position_raw,
    positions.position,
    positions.party_as_recorded,
    positions.state_as_recorded,
    positions.name_as_recorded,
    coalesce(periods.party, positions.party_as_recorded) as party,
    coalesce(
        periods.caucus_party,
        case when positions.party_as_recorded in ('R', 'D') then positions.party_as_recorded end
    ) as caucus_party,
    periods.member_label,
    votes.vote_date between periods.period_start and periods.period_end as term_covers_vote_date
from positions
inner join votes on votes.vote_id = positions.vote_id
left join periods
    on periods.bioguide_id = positions.bioguide_id
    and periods.chamber = votes.chamber
-- Prefer a period covering the vote date; period boundaries can share a day
-- (one term ends the day the next begins), so among those take the latest
-- start. Otherwise take the period nearest the vote date.
qualify row_number() over (
    partition by positions.vote_id, coalesce(positions.bioguide_id, positions.lis_id)
    order by
        (votes.vote_date between periods.period_start and periods.period_end) desc nulls last,
        least(abs(datediff('day', periods.period_start, votes.vote_date)),
              abs(datediff('day', periods.period_end, votes.vote_date))) asc nulls last,
        periods.period_start desc
) = 1
