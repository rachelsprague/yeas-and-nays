-- Bill numbers are digits. Congress.gov values pass through staging as-is;
-- they're escaped where shown, so an odd one warns rather than stopping the run.
{{ config(severity='warn') }}

with numbers as (
    select 'stg_congress_gov__bills' as model, bill_number from {{ ref('stg_congress_gov__bills') }}
    union all
    select 'stg_congress_gov__bill_summaries', bill_number from {{ ref('stg_congress_gov__bill_summaries') }}
    union all
    select 'stg_congress_gov__sponsored_bills', bill_number from {{ ref('stg_congress_gov__sponsored_bills') }}
    union all
    select 'stg_congress_gov__cosponsored_bills', bill_number from {{ ref('stg_congress_gov__cosponsored_bills') }}
    union all
    select 'stg_floor__house_items', bill_number from {{ ref('stg_floor__house_items') }}
    union all
    select 'stg_floor__senate_actions', bill_number from {{ ref('stg_floor__senate_actions') }}
    union all
    select 'stg_house__votes', bill_number from {{ ref('stg_house__votes') }}
    union all
    select 'stg_senate__votes', bill_number from {{ ref('stg_senate__votes') }}
)
select model, bill_number
from numbers
where bill_number is not null
  and not regexp_full_match(bill_number::varchar, '[0-9]+')
