-- Every House term has a district (0 for at-large seats and delegates).
-- Staging reads a district of the wrong type as null, and a null district
-- would label the member with their state only, like an at-large member,
-- so it stops the run here instead.
select bioguide_id, term_start, state
from {{ ref('stg_legislators__terms') }}
where chamber = 'house'
  and district is null
