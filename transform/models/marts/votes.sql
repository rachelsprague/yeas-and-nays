{#- One row per roll call vote, House and Senate. -#}

with votes as (
    select * from {{ ref('int_votes_unioned') }}
),

position_summary as (
    select
        vote_id,
        count(*) as member_count,
        count(*) filter (where voted_against_party_majority) as against_party_majority_count
    from {{ ref('positions') }}
    group by vote_id
)

select
    votes.*,
    {{ congress_gov_url('votes.congress', 'votes.bill_type', 'votes.bill_number') }} as congress_gov_url,
    coalesce(position_summary.member_count, 0) as member_count,
    coalesce(position_summary.against_party_majority_count, 0) as against_party_majority_count
from votes
left join position_summary on position_summary.vote_id = votes.vote_id
