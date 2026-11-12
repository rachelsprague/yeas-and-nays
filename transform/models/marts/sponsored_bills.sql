{#-
  One row per bill or resolution a member introduced (sponsored) this
  Congress, with its latest action as Congress.gov records it, and the most
  recent roll call vote on it, if there has been one.
-#}

with sponsored as (
    select * from {{ ref('stg_congress_gov__sponsored_bills') }}
),

latest_vote as (
    select congress, bill_type, bill_number, vote_id, vote_date
    from {{ ref('int_votes_unioned') }}
    where bill_type is not null
    qualify row_number() over (
        partition by congress, bill_type, bill_number
        order by vote_time_et desc, vote_id desc
    ) = 1
)

select
    sponsored.bioguide_id,
    sponsored.congress || '-' || sponsored.bill_type || '-' || sponsored.bill_number as bill_id,
    sponsored.congress,
    sponsored.bill_type,
    sponsored.bill_number,
    sponsored.title,
    sponsored.introduced_date,
    sponsored.latest_action_date,
    sponsored.latest_action_text,
    sponsored.policy_area,
    {{ congress_gov_url('sponsored.congress', 'sponsored.bill_type', 'sponsored.bill_number') }} as congress_gov_url,
    latest_vote.vote_id as latest_vote_id,
    latest_vote.vote_date as latest_vote_date
from sponsored
left join latest_vote
    on latest_vote.congress = sponsored.congress
    and latest_vote.bill_type = sponsored.bill_type
    and latest_vote.bill_number = sponsored.bill_number
