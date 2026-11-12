-- Positions where the official record lists a member on a date outside their
-- term dates in congress-legislators. These are kept as recorded and matched
-- to the nearest term; this warning lists them so each one gets a look.
{{ config(severity='warn') }}

select vote_id, vote_date, bioguide_id, member_label, position_raw
from {{ ref('positions') }}
where not term_covers_vote_date
