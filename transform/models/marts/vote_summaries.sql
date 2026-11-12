{#-
  One row per vote on a bill or resolution that has a CRS summary: the
  summary of the version in effect when the vote was taken, i.e. the latest
  version whose action date is on or before the vote date. When CRS has only
  summarized a later version, that earliest later summary is used. Either way
  the page labels the version (action_desc, action_date) it describes.
-#}

with votes as (
    select vote_id, vote_date, congress, bill_type, bill_number
    from {{ ref('int_votes_unioned') }}
    where bill_type is not null
),

summaries as (
    select * from {{ ref('stg_congress_gov__bill_summaries') }}
)

select
    votes.vote_id,
    summaries.version_code,
    summaries.action_date,
    summaries.action_desc,
    summaries.updated_at,
    summaries.summary_html
from votes
inner join summaries
    on summaries.congress = votes.congress
    and summaries.bill_type = votes.bill_type
    and summaries.bill_number = votes.bill_number
qualify row_number() over (
    partition by votes.vote_id
    order by
        (summaries.action_date <= votes.vote_date) desc,
        -- On or before the vote: the latest. After it: the earliest.
        case when summaries.action_date <= votes.vote_date then summaries.action_date end desc,
        summaries.action_date asc,
        summaries.updated_at desc
) = 1
