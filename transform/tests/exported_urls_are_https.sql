-- Links to official sources in the exported vote and bill data are https, so
-- a bad scheme (e.g. a `javascript:` URL) stops the run before export rather
-- than reaching a page as a link. Escaping in templates is a separate guard:
-- it keeps a value inside its attribute but doesn't check the scheme.
-- legislation_url is passed through from the Congress.gov API; the others are
-- built here. Member website and contact links are checked in
-- stg_legislators__terms (http or https).
with urls as (
    select 'votes' as model, vote_id as id, 'source_url' as field, source_url as url from {{ ref('votes') }}
    union all
    select 'votes', vote_id, 'congress_gov_url', congress_gov_url from {{ ref('votes') }}
    union all
    select 'bills', bill_id, 'congress_gov_url', congress_gov_url from {{ ref('bills') }}
    union all
    select 'bills', bill_id, 'legislation_url', legislation_url from {{ ref('bills') }}
    union all
    select 'sponsored_bills', bioguide_id || ' ' || bill_id, 'congress_gov_url', congress_gov_url
    from {{ ref('sponsored_bills') }}
    union all
    select 'cosponsored_bills', bioguide_id || ' ' || bill_id, 'congress_gov_url', congress_gov_url
    from {{ ref('cosponsored_bills') }}
)
select model, id, field, url
from urls
where url is not null
  and not starts_with(url, 'https://')
