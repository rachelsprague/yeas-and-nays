-- Positions where the official record lists a member on a date outside their
-- term dates in congress-legislators. These are kept as recorded and matched
-- to the nearest term; this warning lists them so each one gets a look.
-- Positions checked against the House Clerk's vacancy list
-- (clerk.house.gov/Members/ViewVacancies) are left out, by vote and member.
{{ config(severity='warn') }}

with checked (vote_id, bioguide_id) as (
    values
        -- Seat vacant Jan. 3, 2025; the opening roll call lists the member, Not Voting.
        ('h119-1-0001', 'G000578'),
        -- Seat vacant Apr. 22, 2026, the day of these votes; listed Not Voting. The term ends Apr. 21.
        ('h119-2-0130', 'S001157'),
        ('h119-2-0131', 'S001157')
)

select vote_id, vote_date, bioguide_id, member_label, position_raw
from {{ ref('positions') }}
where not term_covers_vote_date
  and not exists (
      select 1 from checked
      where checked.vote_id = positions.vote_id and checked.bioguide_id = positions.bioguide_id
  )
