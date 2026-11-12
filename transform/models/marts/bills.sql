{#-
  One row per bill or resolution with a recorded vote this Congress, from
  Congress.gov: who introduced it (the sponsor), when, and how many
  cosponsors it has.
-#}

select
    congress,
    bill_type,
    bill_number,
    congress || '-' || bill_type || '-' || bill_number as bill_id,
    title,
    introduced_date,
    origin_chamber,
    sponsor_bioguide_id,
    sponsor_full_name,
    cosponsor_count,
    policy_area,
    {{ congress_gov_url('congress', 'bill_type', 'bill_number') }} as congress_gov_url,
    legislation_url,
    updated_at
from {{ ref('stg_congress_gov__bills') }}
