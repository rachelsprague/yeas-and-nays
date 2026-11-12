select
    bioguide_id,
    cast(term_start as date) as term_start,
    cast(affiliation_start as date) as affiliation_start,
    cast(affiliation_end as date) as affiliation_end,
    {{ party_code('party') }} as party,
    {{ party_code('caucus') }} as caucus
from {{ source('staged', 'legislator_party_affiliations') }}
