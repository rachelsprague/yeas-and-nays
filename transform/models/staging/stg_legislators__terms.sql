select
    bioguide_id,
    case term_type when 'rep' then 'house' when 'sen' then 'senate' end as chamber,
    cast(term_start as date) as term_start,
    cast(term_end as date) as term_end,
    state,
    district,
    {{ party_code('party') }} as party,
    {{ party_code('caucus') }} as caucus,
    -- A malformed link (the source has had "hhttps://") is left out rather than shown broken.
    case when regexp_full_match(url, 'https?://[^\s"<>]+') then url end as website_url,
    case when regexp_full_match(contact_form, 'https?://[^\s"<>]+') then contact_form end as contact_form_url,
    phone,
    office
from {{ source('staged', 'legislator_terms') }}
