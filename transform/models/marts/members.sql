{#-
  One row per member who served in the 119th Congress, plus anyone the
  official record lists on a 119th roll call without a 119th term in
  congress-legislators (e.g. a member-elect listed on the opening quorum call
  who never took the seat). Chamber, state, district, party, and caucus
  reflect the member's most recent period of service; positions carry the
  values in effect on each vote's date. Official links (website, contact form,
  phone, office, social media) are filled only for members in office now:
  former members' records keep links that no longer work.
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
),

latest_term as (
    select *
    from {{ ref('stg_legislators__terms') }}
    qualify row_number() over (partition by bioguide_id order by term_start desc) = 1
),

-- One row per member, so a repeated entry in the source can't duplicate a member.
social as (
    select *
    from {{ ref('stg_legislators__social_media') }}
    qualify row_number() over (partition by bioguide_id order by x_url, facebook_url) = 1
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
    people.is_current,
    latest_term.website_url,
    latest_term.contact_form_url,
    latest_term.phone,
    -- For tel: links; null unless the recorded number is a 10-digit U.S. number.
    case when length(regexp_replace(latest_term.phone, '[^0-9]', '', 'g')) = 10
        then '+1' || regexp_replace(latest_term.phone, '[^0-9]', '', 'g') end as phone_tel,
    latest_term.office,
    social.x_url,
    social.facebook_url,
    social.instagram_url,
    social.youtube_url,
    social.mastodon_url
from latest
inner join people on people.bioguide_id = latest.bioguide_id
left join service on service.bioguide_id = latest.bioguide_id
left join latest_term on latest_term.bioguide_id = latest.bioguide_id and people.is_current
left join social on social.bioguide_id = latest.bioguide_id and people.is_current
