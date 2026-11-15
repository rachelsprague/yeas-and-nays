-- As exported_urls_are_https, for the floor schedule. It warns, like the
-- schedule's other tests: the schedule is secondary to votes.
{{ config(severity='warn') }}

select *
from {{ ref('floor_schedule') }}
where congress_gov_url is not null
  and not starts_with(congress_gov_url, 'https://')
