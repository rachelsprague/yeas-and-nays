{#-
  One row per member who served in a Congress on the site (the congresses
  seed), plus anyone the official record lists on a roll call without such a
  term in congress-legislators (e.g. a member-elect listed on the opening
  quorum call who never took the seat). Chamber, state, district, party, and
  caucus reflect the member's most recent period of service; positions carry
  the values in effect on each vote's date. last_congress is the latest
  Congress the member served in or is recorded in, and served_from/served_to
  are their dates in it (member_congresses has every Congress). Official links (website, contact form,
  phone, office, social media) are filled only for members in office now:
  former members' records keep links that no longer work.
-#}

with periods as (
    select * from {{ ref('int_member_periods') }}
),

on_site as (
    select * from periods where overlaps_site_congress
),

recorded as (
    select distinct bioguide_id, chamber
    from {{ ref('int_positions_resolved') }}
    where bioguide_id is not null
),

-- Members on a vote with no term in a Congress on the site: their most recent period in that chamber.
recorded_only as (
    select periods.*
    from periods
    inner join recorded
        on recorded.bioguide_id = periods.bioguide_id
        and recorded.chamber = periods.chamber
    where periods.bioguide_id not in (select bioguide_id from on_site)
    qualify row_number() over (partition by periods.bioguide_id order by periods.period_start desc) = 1
),

member_periods as (
    select * from on_site
    union all
    select * from recorded_only
),

latest as (
    select *
    from member_periods
    qualify row_number() over (partition by bioguide_id order by period_start desc) = 1
),

-- The member's latest Congress on the site.
service as (
    select *
    from {{ ref('member_congresses') }}
    qualify row_number() over (partition by bioguide_id order by congress desc) = 1
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
    service.congress as last_congress,
    service.served_in_congress,
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
