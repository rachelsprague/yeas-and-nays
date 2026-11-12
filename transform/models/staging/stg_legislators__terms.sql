select
    bioguide_id,
    case term_type when 'rep' then 'house' when 'sen' then 'senate' end as chamber,
    cast(term_start as date) as term_start,
    cast(term_end as date) as term_end,
    state,
    district,
    {{ party_code('party') }} as party,
    {{ party_code('caucus') }} as caucus
from {{ source('staged', 'legislator_terms') }}
