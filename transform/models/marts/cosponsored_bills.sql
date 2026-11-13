{#-
  One row per bill or resolution a member cosponsored this Congress, with
  its latest action as Congress.gov records it, and the most recent roll call
  vote on it, if there has been one.
-#}

with cosponsored as (
    select * from {{ ref('stg_congress_gov__cosponsored_bills') }}
),

latest_vote as (
    select * from {{ ref('int_latest_vote_per_bill') }}
)

select
    cosponsored.bioguide_id,
    cosponsored.congress || '-' || cosponsored.bill_type || '-' || cosponsored.bill_number as bill_id,
    cosponsored.congress,
    cosponsored.bill_type,
    cosponsored.bill_number,
    cosponsored.title,
    cosponsored.introduced_date,
    cosponsored.latest_action_date,
    cosponsored.latest_action_text,
    cosponsored.policy_area,
    {{ congress_gov_url('cosponsored.congress', 'cosponsored.bill_type', 'cosponsored.bill_number') }} as congress_gov_url,
    latest_vote.vote_id as latest_vote_id,
    latest_vote.vote_date as latest_vote_date
from cosponsored
left join latest_vote
    on latest_vote.congress = cosponsored.congress
    and latest_vote.bill_type = cosponsored.bill_type
    and latest_vote.bill_number = cosponsored.bill_number
