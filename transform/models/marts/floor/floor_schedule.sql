{#-
  What may come up for a vote, one row per item, from each chamber's own
  floor records. Neither is a promise: items are often moved or dropped.

  House: the measures on the Majority Leader's weekly floor schedule (this
  week and next, when published), grouped by the procedure they're listed
  under. Items removed from the schedule are left out.

  Senate: cloture motions filed and still pending, from the daily floor
  activity. A motion stops pending when the record shows cloture voted on or
  the motion withdrawn, or the document itself disposed of (a nomination
  confirmed, a bill passed), with or without a cloture vote.

  vote_id links an item to the roll call that followed: for the House, the
  first vote in the scheduled week that decides the measure (passage,
  suspend and pass, agreeing to the resolution, concurring, a veto
  override), not procedural
  votes on the way there; for the Senate, the first cloture roll call on it
  after the motion was filed, which can appear before the day's floor
  activity is posted.
-#}

with house_items as (
    select * from {{ ref('stg_floor__house_items') }}
    -- Removal is checked on the recorded value: an unparseable remove date
    -- (null after try_cast) still means removed. A malformed week is dropped
    -- rather than shown undated.
    where removed_at_recorded is null and week_date is not null
),

votes as (
    select * from {{ ref('int_votes_unioned') }}
),

house_decisions as (
    select * from votes
    where chamber = 'house'
        and regexp_matches(
            question,
            '^(On (Passage|Motion to Suspend the Rules and (Pass|Agree|Concur)|Agreeing to the (Resolution|Conference Report)|Motion to Concur)'
            || '|Passage, Objections of the President)',
            'i'
        )
),

house as (
    select
        'house' as chamber,
        'h-' || strftime(items.week_date, '%Y-%m-%d') || '-' || items.item_id as item_id,
        items.week_date,
        null::date as filed_date,
        items.category,
        items.category_order,
        items.item_order,
        null::varchar as question,
        trim(items.measure_number) as measure_number,
        items.bill_type,
        items.bill_number,
        items.title,
        null::varchar as amends,
        {{ congress_gov_url('items.congress', 'items.bill_type', 'items.bill_number') }} as congress_gov_url,
        votes.vote_id,
        votes.vote_date
    from house_items as items
    left join house_decisions as votes
        on votes.congress = items.congress
        and votes.bill_type = items.bill_type
        and votes.bill_number = items.bill_number
        and votes.vote_date between items.week_date and items.week_date + 6
    qualify row_number() over (partition by items.week_date, items.item_id order by votes.vote_time_et, votes.vote_id) = 1
),

events as (
    select * from {{ ref('int_senate_cloture_events') }}
    where activity_date is not null and status_order is not null
),

-- The latest filing for each document and target.
latest_filing as (
    select * from events
    where event = 'filed'
    qualify row_number() over (partition by docnum, target order by activity_date desc, status_order desc) = 1
),

filed as (
    select
        filing.*,
        -- The question as the Senate records it on the roll call.
        case
            when filing.target = 'the motion to proceed to the measure' then 'On Cloture on the Motion to Proceed'
            else 'On the Cloture Motion'
        end as question,
        -- Re-filed the same day an earlier cloture vote on it was taken: that day's roll call is the earlier one.
        exists (
            select 1 from events as voted
            where voted.docnum = filing.docnum
                and voted.target = filing.target
                and voted.event = 'voted'
                and voted.activity_date = filing.activity_date
                and voted.status_order < filing.status_order
        ) as voted_earlier_that_day
    from latest_filing as filing
    where not exists (
        select 1 from events as later
        where later.docnum = filing.docnum
            and (later.activity_date, later.status_order) > (filing.activity_date, filing.status_order)
            and (
                later.event = 'disposed'
                or (later.target = filing.target and later.event in ('voted', 'withdrawn'))
            )
    )
),

senate as (
    select
        'senate' as chamber,
        's-' || filed.docnum || case
            when filed.target = 'the motion to proceed to the measure' then '-proceed'
            when filed.target = 'the measure' then '-measure'
            when filed.target = '' or filed.document_prefix = 'SA' then ''
            else '-' || regexp_replace(lower(filed.target), '[^a-z0-9]+', '-', 'g')
        end as item_id,
        null::date as week_date,
        filed.activity_date as filed_date,
        null::varchar as category,
        null::integer as category_order,
        null::integer as item_order,
        filed.question,
        filed.docnum as measure_number,
        filed.bill_type,
        filed.bill_number,
        filed.document_title as title,
        filed.amends,
        {{ congress_gov_url(var('congress'), 'filed.bill_type', 'filed.bill_number') }} as congress_gov_url,
        votes.vote_id,
        votes.vote_date
    from filed
    left join votes
        on votes.chamber = 'senate'
        and votes.question ilike '%cloture%'
        and (votes.vote_date > filed.activity_date
            or (votes.vote_date = filed.activity_date and not filed.voted_earlier_that_day))
        and case
            when filed.document_prefix = 'SA' then votes.amendment_number = filed.docnum
            when filed.target = 'the motion to proceed to the measure'
                then votes.measure_number = filed.docnum and votes.question ilike '%motion to proceed%'
            -- Cloture on the measure or nomination itself. A motion on anything else
            -- (e.g. a committee substitute) isn't matched rather than guessed at.
            when filed.target in ('the measure', '')
                then votes.measure_number = filed.docnum
                    and votes.amendment_number is null
                    and votes.question not ilike '%motion to proceed%'
            else false
        end
    qualify row_number() over (partition by filed.docnum, filed.target order by votes.vote_time_et, votes.vote_id) = 1
)

select * from house
union all by name
select * from senate
