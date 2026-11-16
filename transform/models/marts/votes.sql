{#- One row per roll call vote, House and Senate. -#}

with votes as (
    select * from {{ ref('int_votes_unioned') }}
),

bills as (
    select * from {{ ref('bills') }}
),

position_summary as (
    select
        vote_id,
        count(*) as member_count,
        count(*) filter (where voted_against_party_majority) as against_party_majority_count
    from {{ ref('positions') }}
    group by vote_id
),

{#- In an Election of the Speaker the Clerk records the result as the top
    candidate's name, in the same form it lists that member among the voters
    ("Johnson (LA)"). Match it to that voter; no match, or more than one,
    leaves it null. #}
result_candidate as (
    select votes.vote_id, any_value(positions.bioguide_id) as result_bioguide_id
    from votes
    inner join {{ ref('int_positions_resolved') }} as positions
        on positions.vote_id = votes.vote_id
        and positions.name_as_recorded = votes.result
    where votes.question = 'Election of the Speaker'
    group by votes.vote_id
    having count(*) = 1
)

select
    votes.*,
    {{ congress_gov_url('votes.congress', 'votes.bill_type', 'votes.bill_number') }} as congress_gov_url,
    bills.sponsor_bioguide_id,
    bills.cosponsor_count,
    bills.policy_area,
    bills.introduced_date,
    result_candidate.result_bioguide_id,
    coalesce(position_summary.member_count, 0) as member_count,
    coalesce(position_summary.against_party_majority_count, 0) as against_party_majority_count
from votes
left join bills
    on bills.congress = votes.congress
    and bills.bill_type = votes.bill_type
    and bills.bill_number = votes.bill_number
left join position_summary on position_summary.vote_id = votes.vote_id
left join result_candidate on result_candidate.vote_id = votes.vote_id
