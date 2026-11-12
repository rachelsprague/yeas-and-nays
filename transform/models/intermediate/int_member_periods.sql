{#-
  One row per member per party-affiliation period, for every term on record.
  overlaps_congress marks periods served during the 119th Congress; earlier
  periods are kept so a vote record can still be matched when the official
  record and congress-legislators disagree on dates (see
  int_positions_resolved). Usually one row per term; a member who changed party
  mid-term gets one row per affiliation period, from the term's
  party_affiliations. Positions join here on vote date to get the party and
  caucus in effect when the vote was cast.

  caucus_party: independents are grouped with the party they caucus with
  (STYLE.md). Members of a major party caucus with their own party.
-#}

with terms as (
    select * from {{ ref('stg_legislators__terms') }}
),

affiliations as (
    select * from {{ ref('stg_legislators__party_affiliations') }}
),

people as (
    select * from {{ ref('stg_legislators__people') }}
),

periods as (
    select
        terms.bioguide_id,
        terms.chamber,
        terms.state,
        terms.district,
        terms.term_start,
        coalesce(affiliations.affiliation_start, terms.term_start) as period_start,
        coalesce(affiliations.affiliation_end, terms.term_end) as period_end,
        case
            when affiliations.bioguide_id is not null then affiliations.party
            else terms.party
        end as party,
        case
            when affiliations.bioguide_id is not null then coalesce(affiliations.caucus, affiliations.party)
            else coalesce(terms.caucus, terms.party)
        end as caucus_party
    from terms
    left join affiliations
        on affiliations.bioguide_id = terms.bioguide_id
        and affiliations.term_start = terms.term_start
)

select
    periods.bioguide_id,
    periods.chamber,
    periods.state,
    periods.district,
    periods.party,
    periods.caucus_party,
    periods.term_start,
    periods.period_start,
    periods.period_end,
    periods.period_end > cast('{{ var("congress_start") }}' as date)
        and periods.period_start < cast('{{ var("congress_end") }}' as date) as overlaps_congress,
    -- Display label per STYLE.md: Murkowski (R-AK), Lawler (R-NY-17).
    -- At-large House seats and delegates (district 0) show the state only.
    people.last_name || ' (' || periods.party || '-' || periods.state
        || case when periods.chamber = 'house' and periods.district > 0 then '-' || periods.district else '' end
        || ')' as member_label
from periods
inner join people on people.bioguide_id = periods.bioguide_id
