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

  decided_* is the House's decision on an item without a roll call (by voice
  vote or without objection), from the Clerk's floor proceedings: the first in
  the scheduled week on a question that decides the measure. Empty when there
  is a roll call. A Senate amendment listed as such has no bill number to
  match on, so it stays undecided rather than guessed at.
-#}

with house_items as (
    select * from {{ ref('stg_floor__house_items') }}
    -- Removal is checked on the recorded value: an unparseable remove date
    -- (null after try_cast) still means removed. A malformed week is dropped
    -- rather than shown undated, and an item ID with no letters or digits
    -- rather than collapsed into a bare week ID.
    where removed_at_recorded is null
        and week_date is not null
        and {{ id_part('item_id') }} is not null
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

-- One per measure and scheduled week, so the join below can't repeat an item.
house_unrecorded as (
    select
        congress, bill_type, bill_number, question, outcome,
        cast(action_time_et as date) as decided_date,
        cast(date_trunc('week', action_time_et) as date) as week_date
    from {{ ref('stg_floor__house_actions') }}
    where outcome is not null and action_time_et is not null and bill_type is not null
    qualify row_number() over (
        partition by congress, bill_type, bill_number, date_trunc('week', action_time_et)
        order by action_time_et, action_id
    ) = 1
),

{%- set house_item_id -%}
    concat_ws('-', 'h', strftime(items.week_date, '%Y-%m-%d'), {{ id_part('items.item_id') }})
{%- endset %}

house as (
    select
        'house' as chamber,
        {{ house_item_id }} as item_id,
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
        votes.vote_date,
        case when votes.vote_id is null then unrecorded.decided_date end as decided_date,
        case when votes.vote_id is null then unrecorded.question end as decided_question,
        case when votes.vote_id is null then unrecorded.outcome end as decided_outcome
    from house_items as items
    left join house_decisions as votes
        on votes.congress = items.congress
        and votes.bill_type = items.bill_type
        and votes.bill_number = items.bill_number
        and votes.vote_date between items.week_date and items.week_date + 6
    left join house_unrecorded as unrecorded
        on unrecorded.congress = items.congress
        and unrecorded.bill_type = items.bill_type
        and unrecorded.bill_number = items.bill_number
        and unrecorded.week_date = items.week_date
    -- One row per item ID, with its first deciding vote. Item IDs the source writes
    -- two ways ("4098.1", "4098-1") share one, and the first in raw order is kept;
    -- the same raw ID listed twice keeps the row listed first on the schedule.
    qualify row_number() over (
        partition by {{ house_item_id }}
        order by items.item_id, items.category_order, items.item_order, items.measure_number, items.title,
            votes.vote_time_et, votes.vote_id
    ) = 1
),

-- docnum_key compares docnums the source writes two ways ("H.R. 4", "H.R.4") as one.
-- An event with no docnum (or one with no letters or digits) can't be told apart
-- from another such event, so it's dropped rather than grouped with them.
events as (
    select *, {{ id_part('docnum') }} as docnum_key
    from {{ ref('int_senate_cloture_events') }}
    where activity_date is not null and status_order is not null and {{ id_part('docnum') }} is not null
),

-- The latest filing for each document and target. Ties (spellings filed in the
-- same status line) go to the first docnum, then title and amends, so the pick is stable.
latest_filing as (
    select * from events
    where event = 'filed'
    qualify row_number() over (
        partition by docnum_key, target
        order by activity_date desc, status_order desc, docnum, document_title, amends
    ) = 1
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
            where voted.docnum_key = filing.docnum_key
                and voted.target = filing.target
                and voted.event = 'voted'
                and voted.activity_date = filing.activity_date
                and voted.status_order < filing.status_order
        ) as voted_earlier_that_day
    from latest_filing as filing
    where not exists (
        select 1 from events as later
        where later.docnum_key = filing.docnum_key
            and (later.activity_date, later.status_order) > (filing.activity_date, filing.status_order)
            and (
                later.event = 'disposed'
                or (later.target = filing.target and later.event in ('voted', 'withdrawn'))
            )
    )
),

{%- set senate_item_id -%}
    concat_ws('-', 's', filed.docnum_key, case
        when filed.target = 'the motion to proceed to the measure' then 'proceed'
        when filed.target = 'the measure' then 'measure'
        when filed.target = '' or filed.document_prefix = 'SA' then null
        else {{ id_part('filed.target') }}
    end)
{%- endset %}

senate as (
    select
        'senate' as chamber,
        {{ senate_item_id }} as item_id,
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
        votes.vote_date,
        null::date as decided_date,
        null::varchar as decided_question,
        null::varchar as decided_outcome
    from filed
    left join votes
        on votes.chamber = 'senate'
        and votes.question ilike '%cloture%'
        and (votes.vote_date > filed.activity_date
            or (votes.vote_date = filed.activity_date and not filed.voted_earlier_that_day))
        and case
            when filed.document_prefix = 'SA' then {{ id_part('votes.amendment_number') }} = filed.docnum_key
            when filed.target = 'the motion to proceed to the measure'
                then {{ id_part('votes.measure_number') }} = filed.docnum_key and votes.question ilike '%motion to proceed%'
            -- Cloture on the measure or nomination itself. A motion on anything else
            -- (e.g. a committee substitute) isn't matched rather than guessed at.
            when filed.target in ('the measure', '')
                then {{ id_part('votes.measure_number') }} = filed.docnum_key
                    and votes.amendment_number is null
                    and votes.question not ilike '%motion to proceed%'
            else false
        end
    -- One row per item ID: a target the source writes two ways gives one, so the
    -- latest filing is kept, with its first cloture vote.
    qualify row_number() over (
        partition by {{ senate_item_id }}
        order by filed.activity_date desc, filed.status_order desc, filed.docnum, filed.target, votes.vote_time_et, votes.vote_id
    ) = 1
)

select * from house
union all by name
select * from senate
