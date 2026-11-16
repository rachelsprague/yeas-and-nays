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
    leaves it null. The Clerk gives candidates by name only, so a non-member
    candidate recorded under a member's bare surname would match that
    member; nothing in the data tells them apart, and no such case is known. #}
result_candidate as (
    select votes.vote_id, any_value(positions.bioguide_id) as result_bioguide_id
    from votes
    inner join {{ ref('int_positions_resolved') }} as positions
        on positions.vote_id = votes.vote_id
        and positions.name_as_recorded = votes.result
    where votes.question = 'Election of the Speaker'
    group by votes.vote_id
    having count(*) = 1
),

votes_counted as (
    select
        votes.*,
        coalesce(position_summary.member_count, 0) as member_count,
        coalesce(position_summary.against_party_majority_count, 0) as against_party_majority_count,
        {#- The Senate records the share each vote needs. The House Clerk marks
            two-thirds votes in the vote type ("2/3 YEA-AND-NAY", expulsions
            included); the question is a fallback: suspending the rules,
            overriding a veto and proposing a constitutional amendment take
            two-thirds of those voting; everything else a majority. Null when
            nothing was tallied as yea or nay (quorum calls, Speaker elections). #}
        case
            when coalesce(votes.yea_count, 0) + coalesce(votes.nay_count, 0) = 0 then null
            when votes.chamber = 'senate' then votes.majority_requirement
            when votes.vote_type like '2/3%'
                or votes.question like 'On Motion to Suspend the Rules%'
                or votes.question like 'Passage, Objections of the President%'
                or (votes.question = 'On Passage'
                    and votes.measure_title ilike 'Proposing an amendment to the Constitution%')
                then '2/3'
            else '1/2'
        end as required_share
    from votes
    left join position_summary on position_summary.vote_id = votes.vote_id
)

select
    votes.*,
    {#- The fewest Yeas that carry the question. A majority or two-thirds is
        of those voting yea or nay; three-fifths (Senate cloture and waivers)
        is of senators duly chosen and sworn, counted here as the senators on
        the roll call (null with no roll). A Vice President's tie-breaking
        vote isn't counted. #}
    case votes.required_share
        when '1/2' then (votes.yea_count + votes.nay_count) // 2 + 1
        when '2/3' then cast(ceil(2 * (votes.yea_count + votes.nay_count) / 3) as integer)
        when '3/5' then cast(ceil(3 * nullif(votes.member_count, 0) / 5) as integer)
    end as yeas_needed,
    {{ congress_gov_url('votes.congress', 'votes.bill_type', 'votes.bill_number') }} as congress_gov_url,
    bills.sponsor_bioguide_id,
    bills.cosponsor_count,
    bills.policy_area,
    bills.introduced_date,
    result_candidate.result_bioguide_id
from votes_counted as votes
left join bills
    on bills.congress = votes.congress
    and bills.bill_type = votes.bill_type
    and bills.bill_number = votes.bill_number
left join result_candidate on result_candidate.vote_id = votes.vote_id
